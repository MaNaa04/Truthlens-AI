"""
Tests for the LLM Judge (Layer 4).
All LLM API calls are mocked.
"""

import pytest
import json
from unittest.mock import patch, MagicMock, AsyncMock
from app.services.judge.llm_judge import LLMJudge
from app.models.response import JudgeResponse


# ── Prompt Building Tests ──────────────────────────────────────────

class TestBuildJudgePrompt:
    """Tests for prompt construction."""

    def test_prompt_contains_all_inputs(self):
        prompt = LLMJudge.build_judge_prompt(
            "What is Paris?", "Paris is a city.", "Evidence here"
        )
        assert "What is Paris?" in prompt
        assert "Paris is a city." in prompt
        assert "Evidence here" in prompt

    def test_prompt_with_empty_evidence(self):
        prompt = LLMJudge.build_judge_prompt(
            "What is Paris?", "Paris is a city.", ""
        )
        assert "No external evidence was retrieved" in prompt

    def test_prompt_requests_json(self):
        prompt = LLMJudge.build_judge_prompt("Q", "A", "E")
        assert "JSON" in prompt
        assert "score" in prompt
        assert "verdict" in prompt


# ── Response Parsing Tests ─────────────────────────────────────────

class TestParseJudgeResponse:
    """Tests for JSON response parsing."""

    def _make_judge(self):
        """Create a judge instance without API connection."""
        with patch("app.services.judge.llm_judge.get_settings") as mock:
            mock.return_value = MagicMock(
                llm_api_key="", llm_model="test", llm_provider="gemini"
            )
            return LLMJudge()

    def test_parse_clean_json(self):
        judge = self._make_judge()
        raw = json.dumps({
            "score": 85,
            "verdict": "verified",
            "explanation": "Evidence confirms.",
            "flag": False
        })
        result = judge._parse_judge_response(raw)
        assert result.score == 85
        assert result.verdict == "verified"

    def test_parse_json_in_code_block(self):
        judge = self._make_judge()
        raw = '```json\n{"score": 90, "verdict": "verified", "explanation": "Confirmed.", "flag": false}\n```'
        result = judge._parse_judge_response(raw)
        assert result.score == 90
        assert result.verdict == "verified"

    def test_parse_json_with_surrounding_text(self):
        judge = self._make_judge()
        raw = 'Here is my analysis:\n{"score": 30, "verdict": "likely_hallucination", "explanation": "Not supported.", "flag": true}\nThank you.'
        result = judge._parse_judge_response(raw)
        assert result.score == 30
        assert result.verdict == "likely_hallucination"

    def test_clamps_score_above_100(self):
        judge = self._make_judge()
        raw = json.dumps({"score": 150, "verdict": "verified", "explanation": "Test", "flag": False})
        result = judge._parse_judge_response(raw)
        assert result.score == 100

    def test_clamps_score_below_0(self):
        judge = self._make_judge()
        raw = json.dumps({"score": -10, "verdict": "verified", "explanation": "Test", "flag": False})
        result = judge._parse_judge_response(raw)
        assert result.score == 0

    def test_invalid_verdict_defaults(self):
        judge = self._make_judge()
        raw = json.dumps({"score": 50, "verdict": "maybe", "explanation": "Test", "flag": False})
        result = judge._parse_judge_response(raw)
        assert result.verdict == "unverifiable"

    def test_no_json_returns_heuristic_fallback(self):
        """When no JSON is found, parser returns heuristic 50/unverifiable."""
        judge = self._make_judge()
        result = judge._parse_judge_response("This has no JSON at all.")
        assert result.score == 50
        assert result.verdict == "unverifiable"


# ── Judge Method Tests ─────────────────────────────────────────────

class TestJudge:
    """Tests for the judge() method."""

    @pytest.mark.asyncio
    @patch("app.services.judge.llm_judge.get_settings")
    async def test_no_api_key_returns_neutral(self, mock_settings):
        mock_settings.return_value = MagicMock(
            llm_api_key="", llm_model="test", llm_provider="gemini"
        )
        judge = LLMJudge()
        result = await judge.judge("Q", "A", "E")

        assert result.score == 50
        assert result.verdict == "unverifiable"

    @pytest.mark.asyncio
    @patch("app.services.judge.llm_judge.get_settings")
    async def test_placeholder_key_returns_neutral(self, mock_settings):
        mock_settings.return_value = MagicMock(
            llm_api_key="your_llm_api_key_here", llm_model="test", llm_provider="gemini"
        )
        judge = LLMJudge()
        result = await judge.judge("Q", "A", "E")

        assert result.score == 50
        assert result.verdict == "unverifiable"

    @pytest.mark.asyncio
    @patch("app.services.judge.llm_judge.get_settings")
    async def test_gemini_success(self, mock_settings):
        mock_settings.return_value = MagicMock(
            llm_api_key="real-key", llm_model="gemini-2.0-flash", llm_provider="gemini"
        )

        judge = LLMJudge()
        judge.api_key = "real-key"
        judge.provider = "gemini"

        # Mock the OpenAI-compat async response
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps({
            "score": 85,
            "verdict": "verified",
            "explanation": "Evidence confirms the claim.",
            "flag": False
        })
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=MagicMock(choices=[mock_choice])
        )
        judge.client = mock_client

        result = await judge.judge("What is Paris?", "Paris is the capital.", "Paris is the capital of France.")

        assert result.score == 85
        assert result.verdict == "verified"

    @pytest.mark.asyncio
    @patch("app.services.judge.llm_judge.get_settings")
    async def test_api_error_returns_neutral(self, mock_settings):
        mock_settings.return_value = MagicMock(
            llm_api_key="real-key", llm_model="gemini-2.0-flash", llm_provider="gemini"
        )

        judge = LLMJudge()
        judge.provider = "gemini"
        judge.api_key = "real-key"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=Exception("API timeout")
        )
        judge.client = mock_client

        result = await judge.judge("Q", "A", "E")

        assert result.score == 50
        assert result.verdict == "unverifiable"


# ── Per-Claim Judging Tests ────────────────────────────────────────

class TestJudgePerClaim:
    """Tests for the judge_per_claim() method."""

    @pytest.mark.asyncio
    @patch("app.services.judge.llm_judge.get_settings")
    async def test_per_claim_success(self, mock_settings):
        mock_settings.return_value = MagicMock(
            llm_api_key="real-key", llm_model="gemini-2.0-flash", llm_provider="gemini"
        )

        judge = LLMJudge()
        judge.api_key = "real-key"
        judge.provider = "gemini"

        per_claim_response = json.dumps([
            {
                "claim_index": 0,
                "claim_text": "Paris is the capital of France",
                "score": 95,
                "verdict": "verified",
                "explanation": "Confirmed by Wikipedia."
            },
            {
                "claim_index": 1,
                "claim_text": "It has 10 million people",
                "score": 30,
                "verdict": "likely_hallucination",
                "explanation": "Paris city proper has about 2.1 million."
            }
        ])

        mock_choice = MagicMock()
        mock_choice.message.content = per_claim_response
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(choices=[mock_choice]))
        judge.client = mock_client

        results = await judge.judge_per_claim(
            "What about Paris?",
            "Paris is the capital of France. It has 10 million people.",
            "Paris is the capital of France. Population: ~2.1 million.",
            ["Paris is the capital of France", "It has 10 million people"],
        )

        assert len(results) == 2
        assert results[0]["verdict"] == "accurate"
        assert results[0]["score"] == 95
        assert results[1]["verdict"] == "hallucination"
        assert results[1]["score"] == 30

    @pytest.mark.asyncio
    @patch("app.services.judge.llm_judge.get_settings")
    async def test_per_claim_empty_claims(self, mock_settings):
        mock_settings.return_value = MagicMock(
            llm_api_key="real-key", llm_model="test", llm_provider="gemini"
        )
        judge = LLMJudge()
        judge.api_key = "real-key"
        judge.client = MagicMock()

        results = await judge.judge_per_claim("Q", "A", "E", [])
        assert results == []

    @pytest.mark.asyncio
    @patch("app.services.judge.llm_judge.get_settings")
    async def test_per_claim_no_client(self, mock_settings):
        mock_settings.return_value = MagicMock(
            llm_api_key="", llm_model="test", llm_provider="gemini"
        )
        judge = LLMJudge()

        results = await judge.judge_per_claim("Q", "A", "E", ["claim1"])
        assert results == []

    @pytest.mark.asyncio
    @patch("app.services.judge.llm_judge.get_settings")
    async def test_per_claim_api_error_returns_empty(self, mock_settings):
        mock_settings.return_value = MagicMock(
            llm_api_key="real-key", llm_model="test", llm_provider="gemini"
        )
        judge = LLMJudge()
        judge.api_key = "real-key"

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(side_effect=Exception("API timeout"))
        judge.client = mock_client

        results = await judge.judge_per_claim("Q", "A", "E", ["claim1"])
        assert results == []


# ── Anthropic Provider Tests ───────────────────────────────────────

class TestAnthropicProvider:
    """Tests for Anthropic Claude provider integration."""

    @patch("app.services.judge.llm_judge.get_settings")
    def test_anthropic_init(self, mock_settings):
        """Test that Anthropic provider initializes correctly."""
        mock_settings.return_value = MagicMock(
            llm_api_key="test-anthropic-key",
            llm_model="claude-sonnet-4-20250514",
            llm_provider="anthropic"
        )
        judge = LLMJudge()
        assert judge.anthropic_client is not None
        assert judge.client is None
        assert judge.model == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    @patch("app.services.judge.llm_judge.get_settings")
    async def test_anthropic_judge_success(self, mock_settings):
        mock_settings.return_value = MagicMock(
            llm_api_key="test-key",
            llm_model="claude-sonnet-4-20250514",
            llm_provider="anthropic"
        )
        judge = LLMJudge()

        # Mock the Anthropic client response
        mock_content = MagicMock()
        mock_content.text = json.dumps({
            "score": 88,
            "verdict": "verified",
            "explanation": "Claude confirms the claim.",
            "flag": False
        })
        mock_response = MagicMock()
        mock_response.content = [mock_content]
        judge.anthropic_client.messages.create = AsyncMock(return_value=mock_response)

        result = await judge.judge("What is Paris?", "Paris is the capital.", "Evidence here.")
        assert result.score == 88
        assert result.verdict == "verified"
