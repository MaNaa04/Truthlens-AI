"""
Tests for request and response models (Layer 1 & 5).
"""

import pytest
from pydantic import ValidationError
from app.models.request import VerifyRequest
from app.models.response import JudgeResponse, VerifyResponse, ClaimResult


# ── VerifyRequest Tests ────────────────────────────────────────────

class TestVerifyRequest:
    """Tests for input validation on VerifyRequest."""

    def test_valid_request(self):
        req = VerifyRequest(
            question="What is the capital of France?",
            answer="The capital of France is Paris."
        )
        assert req.question == "What is the capital of France?"
        assert req.answer == "The capital of France is Paris."

    def test_strips_whitespace(self):
        req = VerifyRequest(
            question="  What is the capital of France?  ",
            answer="  Paris is the capital.  "
        )
        assert req.question == "What is the capital of France?"
        assert req.answer == "Paris is the capital."

    def test_question_too_short(self):
        with pytest.raises(ValidationError) as exc_info:
            VerifyRequest(question="Hi", answer="Paris is the capital of France.")
        assert "String should have at least 5 characters" in str(exc_info.value)

    def test_answer_too_short(self):
        with pytest.raises(ValidationError) as exc_info:
            VerifyRequest(question="What is the capital?", answer="Yes")
        assert "String should have at least 5 characters" in str(exc_info.value)

    def test_question_too_long(self):
        with pytest.raises(ValidationError):
            VerifyRequest(question="x" * 2001, answer="Paris is the capital.")

    def test_answer_too_long(self):
        with pytest.raises(ValidationError):
            VerifyRequest(question="What is the capital?", answer="x" * 5001)

    def test_missing_question(self):
        with pytest.raises(ValidationError):
            VerifyRequest(answer="Paris is the capital of France.")

    def test_missing_answer(self):
        with pytest.raises(ValidationError):
            VerifyRequest(question="What is the capital of France?")


# ── JudgeResponse Tests ───────────────────────────────────────────

class TestJudgeResponse:
    """Tests for JudgeResponse validation."""

    def test_valid_judge_response(self):
        resp = JudgeResponse(
            score=85,
            verdict="verified",
            explanation="Evidence confirms the claim.",
            flag=False
        )
        assert resp.score == 85
        assert resp.verdict == "verified"

    def test_score_below_minimum(self):
        with pytest.raises(ValidationError):
            JudgeResponse(score=-1, verdict="verified", explanation="Test", flag=False)

    def test_score_above_maximum(self):
        with pytest.raises(ValidationError):
            JudgeResponse(score=101, verdict="verified", explanation="Test", flag=False)

    def test_invalid_verdict(self):
        with pytest.raises(ValidationError):
            JudgeResponse(score=50, verdict="invalid", explanation="Test", flag=False)


# ── VerifyResponse Tests ──────────────────────────────────────────

class TestVerifyResponse:
    """Tests for VerifyResponse and verdict mapping."""

    def _make_judge_response(self, score: int) -> JudgeResponse:
        return JudgeResponse(
            score=score,
            verdict="verified" if score >= 60 else "likely_hallucination",
            explanation="Test explanation.",
            flag=score < 60
        )

    def test_accurate_verdict(self):
        """Score >= 75 maps to 'accurate'."""
        judge = self._make_judge_response(85)
        resp = VerifyResponse.from_judge_response(judge)
        assert resp.verdict == "accurate"
        assert resp.score == 85

    def test_uncertain_verdict(self):
        """Score 40-74 maps to 'uncertain'."""
        judge = self._make_judge_response(50)
        resp = VerifyResponse.from_judge_response(judge)
        assert resp.verdict == "uncertain"

    def test_hallucination_verdict(self):
        """Score 0-39 maps to 'hallucination'."""
        judge = self._make_judge_response(20)
        resp = VerifyResponse.from_judge_response(judge)
        assert resp.verdict == "hallucination"

    def test_boundary_accurate(self):
        """Score exactly 75 should be 'accurate'."""
        judge = self._make_judge_response(75)
        resp = VerifyResponse.from_judge_response(judge)
        assert resp.verdict == "accurate"

    def test_boundary_uncertain(self):
        """Score exactly 40 should be 'uncertain'."""
        judge = self._make_judge_response(40)
        resp = VerifyResponse.from_judge_response(judge)
        assert resp.verdict == "uncertain"

    def test_boundary_hallucination(self):
        """Score exactly 39 should be 'hallucination'."""
        judge = self._make_judge_response(39)
        resp = VerifyResponse.from_judge_response(judge)
        assert resp.verdict == "hallucination"

    def test_sources_included(self):
        judge = self._make_judge_response(85)
        resp = VerifyResponse.from_judge_response(judge, sources=["Wikipedia"])
        assert resp.sources_used == ["Wikipedia"]

    def test_request_id_and_timing(self):
        judge = self._make_judge_response(85)
        resp = VerifyResponse.from_judge_response(
            judge,
            request_id="test-id-123",
            processing_time_ms=500
        )
        assert resp.request_id == "test-id-123"
        assert resp.processing_time_ms == 500

    def test_optional_fields_default_none(self):
        judge = self._make_judge_response(85)
        resp = VerifyResponse.from_judge_response(judge)
        assert resp.sources_used is None
        assert resp.request_id is None
        assert resp.processing_time_ms is None


# ── ClaimResult Tests ─────────────────────────────────────────────

class TestClaimResult:
    """Tests for ClaimResult model validation."""

    def test_valid_claim_result(self):
        cr = ClaimResult(
            claim_text="Paris is the capital of France",
            score=92,
            verdict="accurate",
            explanation="Confirmed by Wikipedia.",
            source_text="Paris is the capital of France.",
            start_index=0,
            end_index=31,
        )
        assert cr.score == 92
        assert cr.verdict == "accurate"
        assert cr.start_index == 0

    def test_score_boundary_zero(self):
        cr = ClaimResult(
            claim_text="test", score=0, verdict="hallucination",
            explanation="Wrong."
        )
        assert cr.score == 0

    def test_score_boundary_100(self):
        cr = ClaimResult(
            claim_text="test", score=100, verdict="accurate",
            explanation="Correct."
        )
        assert cr.score == 100

    def test_score_below_0_raises(self):
        with pytest.raises(ValidationError):
            ClaimResult(
                claim_text="test", score=-1, verdict="accurate",
                explanation="Bad."
            )

    def test_score_above_100_raises(self):
        with pytest.raises(ValidationError):
            ClaimResult(
                claim_text="test", score=101, verdict="accurate",
                explanation="Bad."
            )

    def test_invalid_verdict_raises(self):
        with pytest.raises(ValidationError):
            ClaimResult(
                claim_text="test", score=50, verdict="maybe",
                explanation="Bad."
            )

    def test_defaults(self):
        cr = ClaimResult(
            claim_text="test", score=50, verdict="uncertain",
            explanation="Unclear."
        )
        assert cr.source_text == ""
        assert cr.start_index == -1
        assert cr.end_index == -1


# ── VerifyResponse with ClaimResults Tests ─────────────────────────

class TestVerifyResponseWithClaims:
    """Tests for VerifyResponse with claim_results field."""

    def _make_judge_response(self, score: int) -> JudgeResponse:
        return JudgeResponse(
            score=score,
            verdict="verified" if score >= 60 else "likely_hallucination",
            explanation="Test explanation.",
            flag=score < 60
        )

    def test_claim_results_included(self):
        judge = self._make_judge_response(85)
        claims = [
            ClaimResult(
                claim_text="Paris is in France",
                score=95,
                verdict="accurate",
                explanation="Confirmed.",
            )
        ]
        resp = VerifyResponse.from_judge_response(judge, claim_results=claims)
        assert resp.claim_results is not None
        assert len(resp.claim_results) == 1
        assert resp.claim_results[0].score == 95

    def test_claim_results_default_none(self):
        judge = self._make_judge_response(85)
        resp = VerifyResponse.from_judge_response(judge)
        assert resp.claim_results is None

    def test_backward_compatibility(self):
        """VerifyResponse without claim_results still serializes correctly."""
        judge = self._make_judge_response(70)
        resp = VerifyResponse.from_judge_response(judge)
        data = resp.model_dump()
        assert "claim_results" in data
        assert data["claim_results"] is None
        assert data["score"] == 70
