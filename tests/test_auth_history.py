"""
Unit tests — Task 1: User Authentication & Sessions
tests/test_auth_history.py

Coverage:
  1. JWTVerifier  — decode valid token, reject expired / tampered / empty secret
  2. UserHistoryRecord  — Pydantic v2 strict 0-100 score validation, field
                          defaults, UUID round-trip, to_mongo_doc serialisation
  3. Mock repository write  — simulate inserting a record tied to a user_id
                              without requiring a live MongoDB connection

These tests are fully offline (no Redis, no MongoDB, no real HTTP calls).
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from jose import jwt
from pydantic import ValidationError

from app.core.auth import JWTVerifier
from app.models.history import UserHistoryRecord


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

TEST_SECRET = "super-secret-test-key-for-hs256-only"
TEST_ALGO = "HS256"
TEST_USER_ID = "user_abc123"


def _make_token(
    sub: str = TEST_USER_ID,
    secret: str = TEST_SECRET,
    exp_offset: int = 3600,
) -> str:
    """Mint a fresh HS256 token for testing."""
    payload = {
        "sub": sub,
        "exp": int(time.time()) + exp_offset,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, secret, algorithm=TEST_ALGO)


def _make_record(**overrides) -> dict:
    """Return keyword arguments for a valid UserHistoryRecord."""
    defaults = dict(
        user_id=TEST_USER_ID,
        question="What is the capital of France?",
        score=85,
        verdict="accurate",
        cache_hit=False,
    )
    defaults.update(overrides)
    return defaults


# ─────────────────────────────────────────────────────────────────────────────
# Phase 1 — JWTVerifier
# ─────────────────────────────────────────────────────────────────────────────

class TestJWTVerifier:
    """Token decode and validation path tests."""

    def test_decode_valid_token(self):
        """A correctly signed, unexpired token should decode successfully."""
        verifier = JWTVerifier(secret=TEST_SECRET, algorithm=TEST_ALGO)
        token = _make_token()
        claims = verifier.decode(token)
        assert claims["sub"] == TEST_USER_ID

    def test_decode_bearer_prefix_stripped(self):
        """``Bearer `` prefix should be stripped transparently."""
        verifier = JWTVerifier(secret=TEST_SECRET, algorithm=TEST_ALGO)
        token = _make_token()
        claims = verifier.decode(f"Bearer {token}")
        assert claims["sub"] == TEST_USER_ID

    def test_extract_user_id(self):
        """extract_user_id() should return the sub claim string."""
        verifier = JWTVerifier(secret=TEST_SECRET, algorithm=TEST_ALGO)
        token = _make_token(sub="uid-xyz-789")
        uid = verifier.extract_user_id(token)
        assert uid == "uid-xyz-789"

    def test_reject_tampered_token(self):
        """A token signed with a different secret must fail verification."""
        verifier = JWTVerifier(secret=TEST_SECRET, algorithm=TEST_ALGO)
        bad_token = _make_token(secret="wrong-secret")
        with pytest.raises(ValueError, match="JWT verification failed"):
            verifier.decode(bad_token)

    def test_reject_expired_token(self):
        """A token with exp in the past must be rejected."""
        verifier = JWTVerifier(secret=TEST_SECRET, algorithm=TEST_ALGO)
        expired = _make_token(exp_offset=-10)  # expired 10 seconds ago
        with pytest.raises(ValueError, match="expired"):
            verifier.decode(expired)

    def test_reject_garbage_token(self):
        """Arbitrary non-JWT string must raise ValueError."""
        verifier = JWTVerifier(secret=TEST_SECRET, algorithm=TEST_ALGO)
        with pytest.raises(ValueError):
            verifier.decode("not.a.jwt.at.all")

    def test_warn_on_empty_secret(self, caplog):
        """Empty secret should log a warning (constructor doesn't raise)."""
        import logging
        with caplog.at_level(logging.WARNING):
            verifier = JWTVerifier(secret="", algorithm=TEST_ALGO)
        assert "empty secret" in caplog.text.lower()

    def test_extract_user_id_missing_sub(self):
        """Token without sub claim must raise ValueError."""
        verifier = JWTVerifier(secret=TEST_SECRET, algorithm=TEST_ALGO)
        # Craft a token with no sub field
        payload = {"exp": int(time.time()) + 3600, "custom": "value"}
        token = jwt.encode(payload, TEST_SECRET, algorithm=TEST_ALGO)
        with pytest.raises(ValueError, match="sub"):
            verifier.extract_user_id(token)


# ─────────────────────────────────────────────────────────────────────────────
# Phase 3 — UserHistoryRecord Pydantic v2 model
# ─────────────────────────────────────────────────────────────────────────────

class TestUserHistoryRecord:
    """Strict validation and serialisation tests for UserHistoryRecord."""

    # ── Happy path ──────────────────────────────────────────────────────────

    def test_valid_record_created(self):
        """Baseline: a fully specified record should construct without errors."""
        record = UserHistoryRecord(**_make_record())
        assert record.user_id == TEST_USER_ID
        assert record.score == 85
        assert record.verdict == "accurate"
        assert record.cache_hit is False
        assert isinstance(record.request_id, uuid.UUID)
        assert isinstance(record.timestamp, datetime)

    def test_timestamp_defaults_to_utc(self):
        """timestamp should default to the current UTC datetime."""
        before = datetime.now(timezone.utc)
        record = UserHistoryRecord(**_make_record())
        after = datetime.now(timezone.utc)
        assert before <= record.timestamp <= after
        assert record.timestamp.tzinfo is not None

    def test_request_id_auto_generated_as_uuid(self):
        """request_id should be auto-generated as a UUID when not supplied."""
        record = UserHistoryRecord(**_make_record())
        assert isinstance(record.request_id, uuid.UUID)

    def test_explicit_request_id_accepted(self):
        """Callers may supply their own request_id (e.g. from pipeline response)."""
        rid = uuid.uuid4()
        record = UserHistoryRecord(**_make_record(request_id=rid))
        assert record.request_id == rid

    def test_cache_hit_true(self):
        """cache_hit=True records the Redis cache hit correctly."""
        record = UserHistoryRecord(**_make_record(cache_hit=True))
        assert record.cache_hit is True

    # ── Score boundary enforcement ──────────────────────────────────────────

    def test_score_minimum_boundary(self):
        """Score of exactly 0 is valid."""
        record = UserHistoryRecord(**_make_record(score=0))
        assert record.score == 0

    def test_score_maximum_boundary(self):
        """Score of exactly 100 is valid."""
        record = UserHistoryRecord(**_make_record(score=100))
        assert record.score == 100

    def test_score_below_minimum_rejected(self):
        """Score of -1 must raise a ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            UserHistoryRecord(**_make_record(score=-1))
        errors = exc_info.value.errors()
        assert any("score" in str(e) for e in errors)

    def test_score_above_maximum_rejected(self):
        """Score of 101 must raise a ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            UserHistoryRecord(**_make_record(score=101))
        errors = exc_info.value.errors()
        assert any("score" in str(e) for e in errors)

    def test_score_negative_large_rejected(self):
        """Any negative score must be rejected."""
        with pytest.raises(ValidationError):
            UserHistoryRecord(**_make_record(score=-999))

    def test_score_over_100_large_rejected(self):
        """Scores far above 100 must be rejected."""
        with pytest.raises(ValidationError):
            UserHistoryRecord(**_make_record(score=9999))

    # ── user_id validation ──────────────────────────────────────────────────

    def test_user_id_blank_rejected(self):
        """Blank user_id must raise ValidationError."""
        with pytest.raises(ValidationError):
            UserHistoryRecord(**_make_record(user_id=""))

    def test_user_id_whitespace_only_rejected(self):
        """Whitespace-only user_id must raise ValidationError."""
        with pytest.raises(ValidationError):
            UserHistoryRecord(**_make_record(user_id="   "))

    def test_user_id_stripped(self):
        """Leading/trailing whitespace on user_id is normalised."""
        record = UserHistoryRecord(**_make_record(user_id="  uid-xyz  "))
        assert record.user_id == "uid-xyz"

    # ── Immutability (frozen model) ─────────────────────────────────────────

    def test_record_is_frozen(self):
        """UserHistoryRecord must be immutable — no field reassignment."""
        record = UserHistoryRecord(**_make_record())
        with pytest.raises(Exception):   # ValidationError or TypeError
            record.score = 50  # type: ignore[misc]

    # ── Serialisation ───────────────────────────────────────────────────────

    def test_to_mongo_doc_returns_dict(self):
        """to_mongo_doc() must return a plain dict."""
        record = UserHistoryRecord(**_make_record())
        doc = record.to_mongo_doc()
        assert isinstance(doc, dict)

    def test_to_mongo_doc_request_id_is_string(self):
        """request_id must be serialised as a string (not a UUID) in Mongo docs."""
        record = UserHistoryRecord(**_make_record())
        doc = record.to_mongo_doc()
        assert isinstance(doc["request_id"], str)

    def test_to_mongo_doc_preserves_user_id(self):
        """Mongo document user_id must match the model's user_id."""
        record = UserHistoryRecord(**_make_record(user_id="uid-test-999"))
        doc = record.to_mongo_doc()
        assert doc["user_id"] == "uid-test-999"

    def test_to_mongo_doc_all_expected_keys_present(self):
        """Mongo document must contain all required fields."""
        record = UserHistoryRecord(**_make_record())
        doc = record.to_mongo_doc()
        required_keys = {"user_id", "request_id", "question", "score",
                         "verdict", "cache_hit", "timestamp"}
        assert required_keys.issubset(doc.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Phase 4 — Mock repository write (no live MongoDB required)
# ─────────────────────────────────────────────────────────────────────────────

class TestUserHistoryRepositoryMock:
    """
    Simulate persisting a UserHistoryRecord to MongoDB without a live DB.

    We mock ``AsyncIOMotorCollection.insert_one`` so the test is fully offline
    and deterministic.
    """

    @pytest.mark.asyncio
    async def test_insert_record_calls_insert_one(self):
        """
        Verify that UserHistoryRepository.insert() calls collection.insert_one
        with the correct document for a given user_id.
        """
        from app.db.mongo import UserHistoryRepository

        # Build a real record
        rid = uuid.uuid4()
        record = UserHistoryRecord(
            user_id=TEST_USER_ID,
            request_id=rid,
            question="Is the sky blue?",
            score=90,
            verdict="accurate",
            cache_hit=False,
        )

        # Mock the Motor collection
        mock_result = MagicMock()
        mock_result.inserted_id = "507f1f77bcf86cd799439011"
        mock_collection = AsyncMock()
        mock_collection.insert_one = AsyncMock(return_value=mock_result)

        # Mock the database handle
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        repo = UserHistoryRepository(mock_db)
        inserted_id = await repo.insert(record.to_mongo_doc())

        # insert_one was called exactly once
        mock_collection.insert_one.assert_awaited_once()

        # The document passed had the correct user_id
        call_args = mock_collection.insert_one.call_args
        doc_passed = call_args[0][0]  # first positional argument
        assert doc_passed["user_id"] == TEST_USER_ID
        assert doc_passed["score"] == 90
        assert doc_passed["verdict"] == "accurate"
        assert doc_passed["cache_hit"] is False
        assert doc_passed["request_id"] == str(rid)

        # Return value is the inserted id string
        assert inserted_id == "507f1f77bcf86cd799439011"

    @pytest.mark.asyncio
    async def test_list_for_user_calls_find_with_user_id(self):
        """
        Verify that list_for_user() queries the collection with the correct
        user_id filter and applies sort / skip / limit.
        """
        from app.db.mongo import UserHistoryRepository

        # Build mock documents that the cursor would return
        mock_docs = [
            {"user_id": TEST_USER_ID, "score": 80, "verdict": "accurate"},
            {"user_id": TEST_USER_ID, "score": 30, "verdict": "hallucination"},
        ]

        # Build a mock cursor chain: find().sort().skip().limit()
        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=mock_docs)

        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        repo = UserHistoryRepository(mock_db)
        results = await repo.list_for_user(TEST_USER_ID, skip=0, limit=20)

        # find() was called with the user_id filter
        mock_collection.find.assert_called_once_with({"user_id": TEST_USER_ID})

        # Results match our mock documents
        assert len(results) == 2
        assert results[0]["score"] == 80
        assert results[1]["score"] == 30

    @pytest.mark.asyncio
    async def test_list_for_user_converts_objectid(self):
        """Verify that _id of type ObjectId is converted to string representation."""
        from app.db.mongo import UserHistoryRepository
        from bson import ObjectId

        oid = ObjectId()
        mock_docs = [
            {"_id": oid, "user_id": TEST_USER_ID, "score": 80, "verdict": "accurate"}
        ]

        mock_cursor = MagicMock()
        mock_cursor.sort = MagicMock(return_value=mock_cursor)
        mock_cursor.skip = MagicMock(return_value=mock_cursor)
        mock_cursor.limit = MagicMock(return_value=mock_cursor)
        mock_cursor.to_list = AsyncMock(return_value=mock_docs)

        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)

        repo = UserHistoryRepository(mock_db)
        results = await repo.list_for_user(TEST_USER_ID, skip=0, limit=20)

        assert results[0]["_id"] == str(oid)
