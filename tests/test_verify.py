"""
Tests for the /api/verify endpoint (Layer 1).
Uses httpx AsyncClient with mocked downstream services.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
import httpx
from app.models.response import JudgeResponse
from app.services.preprocessing.query_preprocessor import ProcessedQuery
from main import app


# ── Fixtures & Setup ────────────────────────────────────────────────

VALID_PAYLOAD = {
    "question": "What is the capital of France?",
    "answer": "The capital of France is Paris, located along the Seine River."
}

MOCK_PROCESSED = ProcessedQuery(
    original_question="What is the capital of France?",
    original_answer="The capital of France is Paris, located along the Seine River.",
    extracted_claims=["Paris is capital of France"],
    query_type="encyclopedic"
)

MOCK_EVIDENCE_MAP = {
    "Wikipedia": "Paris is the capital and largest city of France."
}

MOCK_JUDGE_RESPONSE = JudgeResponse(
    score=90,
    verdict="verified",
    explanation="Evidence confirms Paris is the capital of France.",
    flag=False
)


@pytest.fixture(autouse=True)
def mock_app_dependencies():
    """
    Autouse fixture that overrides auth dependencies, mocks cache calls, and
    mocks app.state singletons (including MongoDB insert_one mock) so that functional
    verification tests run cleanly and isolated.
    """
    # 1. Override JWT authentication dependency
    from app.api.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: "test_user_123"

    # 2. Mock state singletons
    mock_sr = AsyncMock()
    mock_judge = AsyncMock()
    mock_agg = MagicMock()
    
    # Structure MongoDB mock to support async await insert_one in background tasks
    mock_db = MagicMock()
    mock_collection = AsyncMock()
    mock_collection.insert_one = AsyncMock(return_value=MagicMock(inserted_id="mock_id"))
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    app.state.source_router = mock_sr
    app.state.judge = mock_judge
    app.state.aggregator = mock_agg
    app.state.db = mock_db

    # 3. Patch cache functions to avoid cache pollution between tests
    with patch("app.api.routes.verify.get_cached", new=AsyncMock(return_value=None)), \
         patch("app.api.routes.verify.set_cached", new=AsyncMock()):
        yield mock_sr, mock_judge, mock_agg, mock_db

    # 4. Clean up dependency overrides
    app.dependency_overrides.clear()


# ── Success Path ───────────────────────────────────────────────────

class TestVerifyEndpointSuccess:
    """Tests for the happy path of /api/verify."""

    @pytest.mark.asyncio
    @patch("app.api.routes.verify.QueryPreprocessor")
    async def test_full_pipeline_success(
        self, mock_preprocessor, mock_app_dependencies
    ):
        mock_sr, mock_judge, mock_agg, _ = mock_app_dependencies
        # Setup mocks — all async methods need AsyncMock
        mock_preprocessor.preprocess_async = AsyncMock(return_value=MOCK_PROCESSED)

        mock_sr.retrieve_evidence = AsyncMock(return_value=MOCK_EVIDENCE_MAP)

        mock_agg.aggregate.return_value = "Paris is the capital and largest city of France."

        mock_judge.judge = AsyncMock(return_value=MOCK_JUDGE_RESPONSE)
        mock_judge.judge_per_claim = AsyncMock(return_value=[])

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/verify", json=VALID_PAYLOAD)

        assert response.status_code == 200
        data = response.json()
        assert data["score"] == 90
        assert data["verdict"] == "accurate"
        assert data["explanation"] == "Evidence confirms Paris is the capital of France."
        assert data["flag"] is False
        assert data["sources_used"] == ["Wikipedia"]
        assert "request_id" in data
        assert "processing_time_ms" in data


# ── Validation Errors ─────────────────────────────────────────────

class TestVerifyEndpointValidation:
    """Tests for input validation (Pydantic handles these)."""

    @pytest.mark.asyncio
    async def test_missing_question(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/verify", json={
                "answer": "Paris is the capital of France."
            })
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_answer(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/verify", json={
                "question": "What is the capital of France?"
            })
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_question_too_short(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/verify", json={
                "question": "Hi",
                "answer": "Paris is the capital of France."
            })
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_answer_too_short(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/verify", json={
                "question": "What is the capital?",
                "answer": "Yes"
            })
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_body(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/verify", json={})
        assert response.status_code == 422


# ── Graceful Degradation ──────────────────────────────────────────

class TestVerifyEndpointDegradation:
    """Tests for graceful degradation when services fail."""

    @pytest.mark.asyncio
    @patch("app.api.routes.verify.QueryPreprocessor")
    async def test_retrieval_failure_degrades_gracefully(
        self, mock_preprocessor, mock_app_dependencies
    ):
        """When retrieval fails, pipeline continues with empty evidence."""
        mock_sr, mock_judge, mock_agg, _ = mock_app_dependencies
        mock_preprocessor.preprocess_async = AsyncMock(return_value=MOCK_PROCESSED)

        mock_sr.retrieve_evidence = AsyncMock(side_effect=Exception("Wikipedia API down"))
        mock_agg.aggregate.return_value = ""

        mock_judge.judge = AsyncMock(return_value=JudgeResponse(
            score=50, verdict="unverifiable",
            explanation="No evidence available.", flag=False
        ))
        mock_judge.judge_per_claim = AsyncMock(return_value=[])

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/verify", json=VALID_PAYLOAD)
        assert response.status_code == 200
        data = response.json()
        assert data["verdict"] == "uncertain"  # score 50 → uncertain

    @pytest.mark.asyncio
    @patch("app.api.routes.verify.QueryPreprocessor")
    async def test_judge_failure_returns_neutral(
        self, mock_preprocessor, mock_app_dependencies
    ):
        """When LLM judge fails, return neutral score."""
        mock_sr, mock_judge, mock_agg, _ = mock_app_dependencies
        mock_preprocessor.preprocess_async = AsyncMock(return_value=MOCK_PROCESSED)

        mock_sr.retrieve_evidence = AsyncMock(return_value=MOCK_EVIDENCE_MAP)
        mock_agg.aggregate.return_value = "Some evidence"

        mock_judge.judge = AsyncMock(side_effect=Exception("LLM API timeout"))
        mock_judge.judge_per_claim = AsyncMock(return_value=[])

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/verify", json=VALID_PAYLOAD)
        assert response.status_code == 200
        data = response.json()
        assert data["score"] == 50
        assert data["verdict"] == "uncertain"

    @pytest.mark.asyncio
    @patch("app.api.routes.verify.QueryPreprocessor")
    async def test_preprocessing_failure_returns_500(self, mock_preprocessor):
        """When preprocessing fails, return 500 (can't continue without claims)."""
        mock_preprocessor.preprocess_async = AsyncMock(side_effect=Exception("NLP model failed"))

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/verify", json=VALID_PAYLOAD)
        assert response.status_code == 500


# ── Health Check ──────────────────────────────────────────────────

class TestHealthCheck:
    """Tests for /api/health endpoint."""

    @pytest.mark.asyncio
    async def test_health_check(self):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "hallucination-detection"
