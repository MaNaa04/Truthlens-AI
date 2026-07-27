"""
Shared test fixtures and configuration for pytest.
Provides reusable mock objects, settings, and factory helpers.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.models.response import JudgeResponse, ClaimResult
from app.services.preprocessing.query_preprocessor import ProcessedQuery


# ── Shared Fixtures ────────────────────────────────────────────────

@pytest.fixture
def mock_judge_settings():
    """Provide mocked settings for LLMJudge initialization."""
    with patch("app.services.judge.llm_judge.get_settings") as mock:
        mock.return_value = MagicMock(
            llm_api_key="test-key",
            llm_model="gemini-2.0-flash",
            llm_provider="gemini",
            llm_api_base="",
        )
        yield mock


@pytest.fixture
def mock_judge_no_key():
    """Provide mocked settings with no API key."""
    with patch("app.services.judge.llm_judge.get_settings") as mock:
        mock.return_value = MagicMock(
            llm_api_key="",
            llm_model="test",
            llm_provider="gemini",
        )
        yield mock


@pytest.fixture
def sample_judge_response():
    """Standard successful JudgeResponse for testing."""
    return JudgeResponse(
        score=90,
        verdict="verified",
        explanation="Evidence confirms Paris is the capital of France.",
        flag=False,
    )


@pytest.fixture
def sample_processed_query():
    """Standard ProcessedQuery for testing the verify pipeline."""
    return ProcessedQuery(
        original_question="What is the capital of France?",
        original_answer="The capital of France is Paris, located along the Seine River.",
        extracted_claims=["Paris is capital of France"],
        query_type="encyclopedic",
    )


@pytest.fixture
def sample_claim_results():
    """Sample per-claim results for testing."""
    return [
        ClaimResult(
            claim_text="Paris is the capital of France",
            score=95,
            verdict="accurate",
            explanation="Confirmed by Wikipedia.",
            source_text="Paris is indeed the capital of France.",
            start_index=0,
            end_index=39,
        ),
        ClaimResult(
            claim_text="It is located along the Seine River",
            score=88,
            verdict="accurate",
            explanation="Geographic fact confirmed.",
            source_text="It is located along the Seine River.",
            start_index=40,
            end_index=75,
        ),
    ]


@pytest.fixture
def sample_evidence_map():
    """Standard evidence map from source router."""
    return {
        "Wikipedia": "Paris is the capital and largest city of France."
    }
