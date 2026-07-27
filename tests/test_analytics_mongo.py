"""
Tests for MongoDB-backed analytics tracking (user-scoped).
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone
from fastapi import Request
from jose import jwt

from app.api.dependencies import get_optional_user
from app.services.analytics.tracker import AnalyticsTracker, VerificationEvent
from app.db.mongo import EVENTS_COLLECTION


# ── Dependency tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_optional_user_no_header():
    request = MagicMock(spec=Request)
    request.headers = {}
    
    user_id = await get_optional_user(request)
    assert user_id is None


@pytest.mark.asyncio
async def test_get_optional_user_invalid_header_scheme():
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Basic YWxhZGRpbjpvcGVuc2VzYW1l"}
    
    user_id = await get_optional_user(request)
    assert user_id is None


@pytest.mark.asyncio
async def test_get_optional_user_valid_token():
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer valid_jwt_token"}
    
    mock_verifier = MagicMock()
    mock_verifier.extract_user_id.return_value = "verified_user_123"
    request.app.state.auth_verifier = mock_verifier
    
    user_id = await get_optional_user(request)
    assert user_id == "verified_user_123"
    mock_verifier.extract_user_id.assert_called_once_with("valid_jwt_token")


@pytest.mark.asyncio
async def test_get_optional_user_invalid_token():
    request = MagicMock(spec=Request)
    request.headers = {"Authorization": "Bearer bad_token"}
    
    mock_verifier = MagicMock()
    mock_verifier.extract_user_id.side_effect = ValueError("Token expired")
    request.app.state.auth_verifier = mock_verifier
    
    user_id = await get_optional_user(request)
    assert user_id is None


# ── Analytics Tracker async tests ──────────────────────────────────

@pytest.mark.asyncio
async def test_record_async_inserts_into_db():
    tracker = AnalyticsTracker()
    
    # Mock MongoDB db and collection
    mock_db = MagicMock()
    mock_collection = AsyncMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    
    event = VerificationEvent(
        request_id="test_req_123",
        timestamp=datetime.now(timezone.utc).isoformat(),
        question_preview="What is 2+2?",
        answer_preview="2+2 is 4",
        score=100,
        verdict="accurate",
        sources_used=["Wikipedia"],
        processing_time_ms=100,
        claims_count=1,
        evidence_chars=20,
        provider="gemini",
        query_type="encyclopedic",
        sentences_found=1,
        factual_sentences=1,
        preprocessing_time_ms=10,
        retrieval_time_ms=50,
        judge_time_ms=40,
    )
    
    await tracker.record_async(mock_db, event, user_id="user_abc")
    
    # Verify insert_one was called on collection with the event dict
    mock_db.__getitem__.assert_called_once_with(EVENTS_COLLECTION)
    insert_call_args = mock_collection.insert_one.call_args[0][0]
    assert insert_call_args["request_id"] == "test_req_123"
    assert insert_call_args["user_id"] == "user_abc"
    assert insert_call_args["score"] == 100


@pytest.mark.asyncio
async def test_get_stats_async_empty():
    tracker = AnalyticsTracker()
    
    mock_db = MagicMock()
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = []
    mock_collection = MagicMock()
    mock_collection.find.return_value.sort.return_value = mock_cursor
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    
    stats = await tracker.get_stats_async(mock_db, user_id="user_abc")
    assert stats["total_verifications"] == 0
    assert stats["avg_score"] == 0


@pytest.mark.asyncio
async def test_get_stats_async_with_events():
    tracker = AnalyticsTracker()
    
    mock_db = MagicMock()
    mock_cursor = AsyncMock()
    mock_cursor.to_list.return_value = [
        {
            "request_id": "req_1",
            "timestamp": "2026-05-25T12:00:00Z",
            "score": 90,
            "verdict": "accurate",
            "sources_used": ["Wikipedia"],
            "processing_time_ms": 200,
            "query_type": "encyclopedic",
            "user_id": "user_abc",
        },
        {
            "request_id": "req_2",
            "timestamp": "2026-05-25T13:00:00Z",
            "score": 30,
            "verdict": "hallucination",
            "sources_used": ["SerpAPI"],
            "processing_time_ms": 400,
            "query_type": "recent_event",
            "user_id": "user_abc",
        }
    ]
    mock_collection = MagicMock()
    mock_collection.find.return_value.sort.return_value = mock_cursor
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    
    stats = await tracker.get_stats_async(mock_db, user_id="user_abc")
    
    # Assert correctness
    assert stats["total_verifications"] == 2
    assert stats["avg_score"] == 60.0
    assert stats["avg_processing_time_ms"] == 300
    assert stats["verdict_distribution"] == {"accurate": 1, "hallucination": 1}
    assert stats["score_distribution"]["80-100"] == 1
    assert stats["score_distribution"]["20-39"] == 1
    assert stats["sources_distribution"] == {"Wikipedia": 1, "SerpAPI": 1}
    assert len(stats["recent_trend"]) == 2


@pytest.mark.asyncio
async def test_clear_async():
    tracker = AnalyticsTracker()
    
    mock_db = MagicMock()
    mock_collection = AsyncMock()
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)
    
    await tracker.clear_async(mock_db, user_id="user_abc")
    mock_collection.delete_many.assert_called_once_with({"user_id": "user_abc"})


@pytest.mark.asyncio
async def test_get_events_async_converts_objectid():
    tracker = AnalyticsTracker()
    from bson import ObjectId

    oid = ObjectId()
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.limit = MagicMock(return_value=mock_cursor)
    mock_cursor.to_list = AsyncMock(return_value=[
        {
            "_id": oid,
            "request_id": "req_1",
            "timestamp": "2026-05-25T12:00:00Z",
            "score": 90,
            "verdict": "accurate",
            "sources_used": ["Wikipedia"],
            "processing_time_ms": 200,
            "query_type": "encyclopedic",
            "user_id": "user_abc",
        }
    ])
    mock_collection = MagicMock()
    mock_collection.find.return_value.sort.return_value = mock_cursor
    mock_db.__getitem__ = MagicMock(return_value=mock_collection)

    events = await tracker.get_events_async(mock_db, user_id="user_abc", limit=50)
    assert len(events) == 1
    assert events[0]["_id"] == str(oid)
