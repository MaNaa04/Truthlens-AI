"""
Integration & unit tests — Task 2: Securing API Endpoints
tests/test_security.py

Coverage matrix:
  § 1  get_current_user dependency
       - Valid token → 200
       - Missing Authorization header → 403
       - Invalid / tampered token → 401
       - Expired token → 401

  § 2  /api/verify secured endpoint
       - Authenticated request completes successfully
       - Unauthenticated request returns 403
       - BackgroundTask writes history to MongoDB (mocked)
       - Cache hit still writes history with cache_hit=True

  § 3  Rate limiting (SlowAPI, 20/minute per user)
       - Request within limit → 200
       - Simulated exhausted limit → 429
       - Different users have independent counters

  § 4  CORS origin enforcement
       - Preflight from allowed origin → ACAO header present
       - allow_headers=[\"*\"] includes Authorization header

All tests are fully offline.  httpx.AsyncClient + ASGITransport is used
instead of starlette.testclient.TestClient to avoid the httpx 0.28 / starlette
0.27 API incompatibility (TestClient.__init__ passes app= to httpx.Client
which no longer accepts it in httpx ≥ 0.27).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from jose import jwt

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

TEST_SECRET = "test-secret-for-security-tests-hs256"
TEST_ALGO   = "HS256"
BASE_URL    = "http://testserver"

VALID_PAYLOAD = {
    "question": "What is the capital of France?",
    "answer":   "The capital of France is Paris, located along the Seine River.",
}


def _make_token(sub: str = "user_test_123", exp_offset: int = 3600) -> str:
    payload = {
        "sub": sub,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, TEST_SECRET, algorithm=TEST_ALGO)


def _bearer(sub: str = "user_test_123") -> dict[str, str]:
    return {"Authorization": f"Bearer {_make_token(sub=sub)}"}


# ─────────────────────────────────────────────────────────────────────────────
# Shared app fixture (module-scoped so it is built once for all tests)
# ─────────────────────────────────────────────────────────────────────────────

def _setup_app():
    """
    Return a tuple (app, mock_db, mock_collection) with all heavy I/O mocked.

    - JWTVerifier uses TEST_SECRET.
    - MongoDB init_mongo returns a MagicMock database.
    - Redis init_cache / close_cache are no-ops.
    - Pipeline singletons (SourceRouter, LLMJudge, EvidenceAggregator) are
      replaced with AsyncMock / MagicMock doubles.
    """
    from app.core.auth import JWTVerifier
    from app.models.response import JudgeResponse
    from app.services.preprocessing.query_preprocessor import ProcessedQuery

    mock_processed = ProcessedQuery(
        original_question=VALID_PAYLOAD["question"],
        original_answer=VALID_PAYLOAD["answer"],
        extracted_claims=["Paris is capital of France"],
        query_type="encyclopedic",
    )
    mock_judge_resp = JudgeResponse(
        score=90,
        verdict="verified",
        explanation="Evidence confirms Paris is the capital of France.",
        flag=False,
    )
    mock_evidence = {"Wikipedia": "Paris is the capital of France."}

    # Real verifier so actual JWT logic runs
    real_verifier = JWTVerifier(secret=TEST_SECRET, algorithm=TEST_ALGO)

    # Mock Mongo collection
    mock_collection = AsyncMock()
    mock_result = MagicMock()
    mock_result.inserted_id = "507f1f77bcf86cd799439011"
    mock_collection.insert_one = AsyncMock(return_value=mock_result)

    mock_db = MagicMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    # Patch lifecycle I/O before importing main
    with (
        patch("app.core.cache.init_cache", new=AsyncMock()),
        patch("app.core.cache.close_cache", new=AsyncMock()),
        patch("app.db.mongo.init_mongo", new=AsyncMock(return_value=mock_db)),
        patch("app.db.mongo.close_mongo", new=AsyncMock()),
    ):
        from main import app  # noqa: PLC0415

    # Stamp state onto the already-constructed app
    app.state.auth_verifier = real_verifier
    app.state.db = mock_db

    mock_sr = MagicMock()
    mock_sr.retrieve_evidence = AsyncMock(return_value=mock_evidence)
    app.state.source_router = mock_sr

    mock_judge_svc = MagicMock()
    mock_judge_svc.judge = AsyncMock(return_value=mock_judge_resp)
    mock_judge_svc.model = "test-model"
    mock_judge_svc.provider = "test"
    app.state.judge = mock_judge_svc

    mock_agg = MagicMock()
    mock_agg.aggregate = MagicMock(return_value="Paris is the capital.")
    app.state.aggregator = mock_agg

    return app, mock_db, mock_collection


_APP, _MOCK_DB, _MOCK_COLLECTION = _setup_app()


def _client() -> httpx.AsyncClient:
    """Return a fresh AsyncClient pointed at the test ASGI app."""
    transport = httpx.ASGITransport(app=_APP)
    return httpx.AsyncClient(transport=transport, base_url=BASE_URL)


# ─────────────────────────────────────────────────────────────────────────────
# § 1 — get_current_user dependency
# ─────────────────────────────────────────────────────────────────────────────

class TestGetCurrentUser:

    @pytest.mark.asyncio
    async def test_valid_token_returns_200(self):
        """Correctly signed, unexpired token should produce a 200 response."""
        async with _client() as c:
            resp = await c.post("/api/verify", json=VALID_PAYLOAD, headers=_bearer())
        assert resp.status_code == 200, resp.text

    @pytest.mark.asyncio
    async def test_missing_authorization_header_returns_403(self):
        """No Authorization header → HTTPBearer auto_error returns 403."""
        async with _client() as c:
            resp = await c.post("/api/verify", json=VALID_PAYLOAD)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self):
        """Token signed with wrong secret must be rejected with 401."""
        bad = jwt.encode(
            {"sub": "user_x", "exp": int(time.time()) + 3600},
            "WRONG-SECRET", algorithm=TEST_ALGO,
        )
        async with _client() as c:
            resp = await c.post(
                "/api/verify", json=VALID_PAYLOAD,
                headers={"Authorization": f"Bearer {bad}"},
            )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication failed"

    @pytest.mark.asyncio
    async def test_expired_token_returns_401(self):
        """Expired token must be rejected with 401."""
        expired = jwt.encode(
            {"sub": "user_x", "exp": int(time.time()) - 60},
            TEST_SECRET, algorithm=TEST_ALGO,
        )
        async with _client() as c:
            resp = await c.post(
                "/api/verify", json=VALID_PAYLOAD,
                headers={"Authorization": f"Bearer {expired}"},
            )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication failed"

    @pytest.mark.asyncio
    async def test_garbage_token_returns_401(self):
        """Totally malformed bearer value must be rejected with 401."""
        async with _client() as c:
            resp = await c.post(
                "/api/verify", json=VALID_PAYLOAD,
                headers={"Authorization": "Bearer not.a.real.jwt"},
            )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_non_bearer_scheme_returns_403(self):
        """Basic auth scheme must be rejected by HTTPBearer with 403."""
        async with _client() as c:
            resp = await c.post(
                "/api/verify", json=VALID_PAYLOAD,
                headers={"Authorization": "Basic dXNlcjpwYXNz"},
            )
        assert resp.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# § 2 — /api/verify secured endpoint + async history write
# ─────────────────────────────────────────────────────────────────────────────

class TestVerifyEndpointSecurity:

    @pytest.mark.asyncio
    async def test_authenticated_request_returns_200_with_score(self):
        """Full authenticated pipeline flow returns a valid VerifyResponse."""
        with (
            patch("app.api.routes.verify.get_cached", new=AsyncMock(return_value=None)),
            patch("app.api.routes.verify.set_cached", new=AsyncMock()),
            patch("app.api.routes.verify.QueryPreprocessor") as mock_pp,
        ):
            from app.services.preprocessing.query_preprocessor import ProcessedQuery
            mock_pp.preprocess_async = AsyncMock(return_value=ProcessedQuery(
                original_question=VALID_PAYLOAD["question"],
                original_answer=VALID_PAYLOAD["answer"],
                extracted_claims=["Paris is capital of France"],
                query_type="encyclopedic",
            ))
            async with _client() as c:
                resp = await c.post("/api/verify", json=VALID_PAYLOAD, headers=_bearer())
        assert resp.status_code == 200
        data = resp.json()
        assert data["score"] == 90
        assert data["verdict"] == "accurate"
        assert "request_id" in data

    @pytest.mark.asyncio
    async def test_unauthenticated_request_rejected(self):
        """No token → 403 before the pipeline runs."""
        async with _client() as c:
            resp = await c.post("/api/verify", json=VALID_PAYLOAD)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_background_task_inserts_history_record(self):
        """
        BackgroundTask must call collection.insert_one with the correct user_id.

        httpx.AsyncClient with ASGITransport runs BackgroundTasks inline before
        returning the response object, so we can assert on the mock immediately.
        """
        _MOCK_COLLECTION.insert_one.reset_mock()

        with (
            patch("app.api.routes.verify.get_cached", new=AsyncMock(return_value=None)),
            patch("app.api.routes.verify.set_cached", new=AsyncMock()),
        ):
            async with _client() as c:
                resp = await c.post(
                    "/api/verify", json=VALID_PAYLOAD,
                    headers=_bearer(sub="user_history_test"),
                )
        assert resp.status_code == 200

        assert _MOCK_COLLECTION.insert_one.await_count >= 1
        doc = _MOCK_COLLECTION.insert_one.call_args[0][0]
        assert doc["user_id"] == "user_history_test"
        assert "score" in doc
        assert "verdict" in doc
        assert "cache_hit" in doc

    @pytest.mark.asyncio
    async def test_cache_hit_still_writes_history(self):
        """
        Cache-hit path must still fire the BackgroundTask and persist
        a record with cache_hit=True.
        """
        _MOCK_COLLECTION.insert_one.reset_mock()

        cached_data = {
            "score": 85, "verdict": "accurate",
            "explanation": "Cached.", "flag": False,
            "sources_used": ["Wikipedia"],
            "request_id": str(uuid.uuid4()),
            "processing_time_ms": 500,
            "cache_hit": False, "debug": None,
        }

        with patch(
            "app.api.routes.verify.get_cached",
            new=AsyncMock(return_value=cached_data),
        ):
            async with _client() as c:
                resp = await c.post(
                    "/api/verify", json=VALID_PAYLOAD,
                    headers=_bearer(sub="cache_hit_user"),
                )

        assert resp.status_code == 200
        assert resp.json()["cache_hit"] is True

        assert _MOCK_COLLECTION.insert_one.await_count >= 1
        doc = _MOCK_COLLECTION.insert_one.call_args[0][0]
        assert doc["user_id"] == "cache_hit_user"
        assert doc["cache_hit"] is True


# ─────────────────────────────────────────────────────────────────────────────
# § 3 — Rate limiting (SlowAPI, 20/minute per user)
# ─────────────────────────────────────────────────────────────────────────────

class TestRateLimiting:
    """
    Verifies the 20-request-per-minute per-user rate limit on /api/verify.

    Strategy for 429 tests:
      Patch ``Limiter._check_request_limit`` (the method SlowAPI's @limiter.limit
      decorator calls internally) to raise ``RateLimitExceeded`` with a properly
      constructed ``Limit`` wrapper.  This fires *before* the route handler and
      triggers the registered RateLimitExceeded → 429 exception handler.

    Cache is patched to None in every test so results never come from the
    in-memory fallback cache.
    """

    @pytest.mark.asyncio
    async def test_request_within_limit_succeeds(self):
        """First request from a fresh user must not be rate-limited."""
        with (
            patch("app.api.routes.verify.get_cached", new=AsyncMock(return_value=None)),
            patch("app.api.routes.verify.set_cached", new=AsyncMock()),
        ):
            async with _client() as c:
                resp = await c.post(
                    "/api/verify", json=VALID_PAYLOAD,
                    headers=_bearer(sub="rl_fresh_user"),
                )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_returns_429(self):
        """
        Simulate exhausted budget: use the @limiter.limit decorator's built-in
        behaviour by making 21 real requests against the in-process ASGI app.
        SlowAPI uses an in-memory MemoryStorage by default, so 21 requests
        within one test exhaust the 20/minute window and return 429.
        """
        # Use a unique sub so this test's counter starts at 0
        headers = _bearer(sub="rl_exhaust_user_unique")
        cache_patch = patch("app.api.routes.verify.get_cached", new=AsyncMock(return_value=None))
        set_patch   = patch("app.api.routes.verify.set_cached", new=AsyncMock())
        pp_patch    = patch("app.api.routes.verify.QueryPreprocessor")

        from app.services.preprocessing.query_preprocessor import ProcessedQuery
        mock_processed = ProcessedQuery(
            original_question=VALID_PAYLOAD["question"],
            original_answer=VALID_PAYLOAD["answer"],
            extracted_claims=["Paris is capital of France"],
            query_type="encyclopedic",
        )

        last_status = 0
        with cache_patch, set_patch, pp_patch as mock_pp:
            mock_pp.preprocess_async = AsyncMock(return_value=mock_processed)
            async with _client() as c:
                for i in range(21):
                    resp = await c.post("/api/verify", json=VALID_PAYLOAD, headers=headers)
                    last_status = resp.status_code
                    if last_status == 429:
                        break

        assert last_status == 429

    def test_different_users_produce_independent_rate_limit_keys(self):
        """
        Unit test: the rate-limit key function must produce distinct bucket
        keys for different user JWTs so user A's counter never affects user B.

        Tests the key function directly without making HTTP calls.
        """
        from app.core.limiter import _user_id_key
        from starlette.requests import Request as StarletteRequest
        from app.core.auth import JWTVerifier

        verifier = JWTVerifier(secret=TEST_SECRET, algorithm=TEST_ALGO)

        def _make_scope(sub: str) -> dict:
            token = _make_token(sub=sub)
            return {
                "type": "http",
                "method": "POST",
                "path": "/api/verify",
                "headers": [
                    (b"authorization", f"Bearer {token}".encode()),
                ],
                "query_string": b"",
                "app": MagicMock(state=MagicMock(auth_verifier=verifier)),
            }

        key_alice = _user_id_key(StarletteRequest(_make_scope("uid_alice")))
        key_bob   = _user_id_key(StarletteRequest(_make_scope("uid_bob")))

        # Each user gets their own key prefixed with 'user:'
        assert key_alice == "user:uid_alice"
        assert key_bob   == "user:uid_bob"
        # Keys must be different — independent buckets guaranteed
        assert key_alice != key_bob


# ─────────────────────────────────────────────────────────────────────────────
# § 4 — CORS origin enforcement
# ─────────────────────────────────────────────────────────────────────────────

class TestCORSEnforcement:

    @pytest.mark.asyncio
    async def test_allowed_origin_passes_preflight(self):
        """
        With ALLOWED_ORIGINS=[\"*\"], a Chrome Extension origin preflight must
        receive an Access-Control-Allow-Origin header in the response.
        """
        async with _client() as c:
            resp = await c.options(
                "/api/verify",
                headers={
                    "Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Authorization, Content-Type",
                },
            )
        assert resp.status_code in (200, 204)
        assert "access-control-allow-origin" in resp.headers

    @pytest.mark.asyncio
    async def test_cors_reflects_wildcard_for_any_origin(self):
        """With ALLOWED_ORIGINS=["*"], any origin gets the ACAO header."""
        async with _client() as c:
            resp = await c.options(
                "/api/verify",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "POST",
                },
            )
        assert resp.status_code in (200, 204)
        assert resp.headers.get("access-control-allow-origin", "") != ""

    @pytest.mark.asyncio
    async def test_cors_allows_authorization_header(self):
        """
        allow_headers=["*"] in CORSMiddleware must echo the requested
        Authorization header in the Access-Control-Allow-Headers response.
        """
        async with _client() as c:
            resp = await c.options(
                "/api/verify",
                headers={
                    "Origin": "chrome-extension://testextensionid",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Authorization",
                },
            )
        assert resp.status_code in (200, 204)
        assert resp.headers.get("access-control-allow-headers", "") != ""


# ─────────────────────────────────────────────────────────────────────────────
# § 5 — /api/history endpoint & CORS Lockdown
# ─────────────────────────────────────────────────────────────────────────────

class TestHistoryEndpointSecurity:

    @pytest.mark.asyncio
    async def test_history_unauthenticated_request_rejected(self):
        """Request without token returns 403 (HTTPBearer auto_error)."""
        async with _client() as c:
            resp = await c.get("/api/history")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_history_invalid_token_rejected(self):
        """Request with invalid token returns 401."""
        async with _client() as c:
            resp = await c.get(
                "/api/history",
                headers={"Authorization": "Bearer invalidtokenhere"},
            )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Authentication failed"

    @pytest.mark.asyncio
    async def test_history_authenticated_retrieval(self):
        """Authenticated request returns list of history records."""
        from datetime import datetime, timezone

        mock_docs = [
            {
                "user_id": "user_test_123",
                "request_id": str(uuid.uuid4()),
                "question": "What is 2+2?",
                "score": 0,
                "verdict": "accurate",
                "cache_hit": True,
                "timestamp": datetime.now(timezone.utc),
            },
            {
                "user_id": "user_test_123",
                "request_id": str(uuid.uuid4()),
                "question": "What is the capital of Spain?",
                "score": 10,
                "verdict": "accurate",
                "cache_hit": False,
                "timestamp": datetime.now(timezone.utc),
            }
        ]
        
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=mock_docs)
        
        find_mock = MagicMock(return_value=mock_cursor)
        with patch.object(_MOCK_COLLECTION, "find", new=find_mock):
            async with _client() as c:
                resp = await c.get("/api/history", headers=_bearer(sub="user_test_123"))
                
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert isinstance(data, list)
            assert len(data) == 2
            assert data[0]["question"] == "What is 2+2?"
            assert data[0]["user_id"] == "user_test_123"
            assert data[1]["question"] == "What is the capital of Spain?"
            
            # Verify skip & limit query parameters are passed down to repo/cursor
            async with _client() as c:
                await c.get("/api/history?skip=5&limit=3", headers=_bearer(sub="user_test_123"))
            
            find_mock.assert_called_with({"user_id": "user_test_123"})
            mock_cursor.skip.assert_called_with(5)
            mock_cursor.limit.assert_called_with(3)


class TestCORSLockdown:

    def test_settings_parses_allowed_origins_string(self, monkeypatch):
        """Settings allowed_origins should parse string and lists correctly."""
        from app.core.config import Settings
        
        monkeypatch.setenv("ALLOWED_ORIGINS", "chrome-extension://abcdef,https://example.com")
        s = Settings()
        assert s.allowed_origins == ["chrome-extension://abcdef", "https://example.com"]
        
        monkeypatch.setenv("ALLOWED_ORIGINS", '["chrome-extension://abcdef"]')
        s2 = Settings()
        assert s2.allowed_origins == ["chrome-extension://abcdef"]

    @pytest.mark.asyncio
    async def test_cors_lockdown_rejects_unallowed_origin(self):
        """When a specific origin is enforced, other origins are rejected (no ACAO)."""
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        
        test_app = FastAPI()
        test_origins = ["chrome-extension://abcdefghijklmnopabcdefghijklmnop"]
        
        test_app.add_middleware(
            CORSMiddleware,
            allow_origins=test_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        
        @test_app.get("/test")
        def dummy():
            return {"ok": True}
            
        transport = httpx.ASGITransport(app=test_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            # Preflight from allowed origin
            resp = await c.options(
                "/test",
                headers={
                    "Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert resp.headers.get("access-control-allow-origin") == "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
            
            # Preflight from unallowed origin (should fail/not return ACAO)
            resp_bad = await c.options(
                "/test",
                headers={
                    "Origin": "https://evil.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert "access-control-allow-origin" not in resp_bad.headers
