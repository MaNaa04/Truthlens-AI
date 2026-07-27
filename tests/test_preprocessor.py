"""
Tests for the Query Preprocessor (Layer 2).
"""

import pytest
from app.services.preprocessing.query_preprocessor import QueryPreprocessor, ProcessedQuery


# ── Claim Extraction Tests ─────────────────────────────────────────

class TestExtractClaims:
    """Tests for extract_claims()."""

    def test_multi_sentence_answer(self):
        answer = (
            "Paris is the capital and largest city of France. "
            "It is located along the Seine River. "
            "The city has a population of over 2 million people."
        )
        claims = QueryPreprocessor.extract_claims(answer)
        assert len(claims) > 0
        assert len(claims) <= 3

    def test_single_factual_sentence(self):
        answer = "The Great Wall of China is over 13,000 miles long."
        claims = QueryPreprocessor.extract_claims(answer)
        assert len(claims) == 1
        assert "Great Wall" in claims[0]

    def test_filters_questions(self):
        answer = (
            "Paris is the capital of France. "
            "Did you know that? "
            "It is also known as the City of Light."
        )
        claims = QueryPreprocessor.extract_claims(answer)
        # "Did you know that?" should be filtered out
        for claim in claims:
            assert not claim.endswith("?")

    def test_filters_filler_phrases(self):
        answer = (
            "In summary, here are the key facts. "
            "London is the capital of England. "
            "I hope this helps you."
        )
        claims = QueryPreprocessor.extract_claims(answer)
        # Only "London is the capital of England" should remain
        assert len(claims) == 1
        assert "London" in claims[0]

    def test_strips_leading_connectors(self):
        answer = (
            "Water boils at 100 degrees Celsius. "
            "However, this temperature varies with altitude. "
            "Also, the boiling point changes under pressure."
        )
        claims = QueryPreprocessor.extract_claims(answer)
        for claim in claims:
            assert not claim.lower().startswith("however")
            assert not claim.lower().startswith("also")

    def test_respects_max_claims(self):
        answer = (
            "The Earth orbits the Sun. "
            "Mars is the fourth planet from the Sun. "
            "Jupiter is the largest planet. "
            "Saturn has distinctive rings. "
            "Venus is the hottest planet."
        )
        claims = QueryPreprocessor.extract_claims(answer, max_claims=2)
        assert len(claims) <= 2

    def test_empty_answer(self):
        claims = QueryPreprocessor.extract_claims("")
        assert claims == []

    def test_very_short_answer(self):
        claims = QueryPreprocessor.extract_claims("Yes")
        assert claims == []

    def test_handles_abbreviations(self):
        answer = "Dr. Smith works at the U.S. National Institutes of Health. He leads the research team."
        claims = QueryPreprocessor.extract_claims(answer)
        # Should not split on "Dr." or "U.S."
        assert any("Dr. Smith" in c or "U.S." in c for c in claims)


# ── Query Type Detection Tests ─────────────────────────────────────

class TestDetermineQueryType:
    """Tests for determine_query_type()."""

    def test_encyclopedic_who(self):
        assert QueryPreprocessor.determine_query_type("Who invented the telephone?") == "encyclopedic"

    def test_encyclopedic_what(self):
        assert QueryPreprocessor.determine_query_type("What is the capital of France?") == "encyclopedic"

    def test_encyclopedic_where(self):
        assert QueryPreprocessor.determine_query_type("Where is Mount Everest located?") == "encyclopedic"

    def test_recent_event_today(self):
        assert QueryPreprocessor.determine_query_type("What happened today in politics?") == "recent_event"

    def test_recent_event_year(self):
        assert QueryPreprocessor.determine_query_type("What were the top events of 2025?") == "recent_event"

    def test_recent_event_latest(self):
        assert QueryPreprocessor.determine_query_type("What is the latest news on AI?") == "recent_event"

    def test_numeric_how_many(self):
        assert QueryPreprocessor.determine_query_type("How many countries are in the EU?") == "numeric_statistical"

    def test_numeric_how_much(self):
        assert QueryPreprocessor.determine_query_type("How much does a Tesla Model 3 cost?") == "numeric_statistical"

    def test_numeric_population(self):
        assert QueryPreprocessor.determine_query_type("What is the population of India?") == "numeric_statistical"

    def test_opinion_should(self):
        assert QueryPreprocessor.determine_query_type("Should I learn Python or JavaScript?") == "opinion_subjective"

    def test_opinion_recommend(self):
        assert QueryPreprocessor.determine_query_type("What do you recommend for dinner?") == "opinion_subjective"

    def test_opinion_better(self):
        assert QueryPreprocessor.determine_query_type("What's better, Mac or Windows?") == "opinion_subjective"


# ── Full Preprocessing Pipeline ────────────────────────────────────

class TestPreprocess:
    """Tests for the full preprocess_async() pipeline."""

    @pytest.mark.asyncio
    async def test_returns_processed_query(self):
        result = await QueryPreprocessor.preprocess_async(
            "What is the capital of France?",
            "Paris is the capital of France. It is located in northern France."
        )
        assert isinstance(result, ProcessedQuery)
        assert result.original_question == "What is the capital of France?"
        assert result.query_type == "encyclopedic"
        assert len(result.extracted_claims) > 0

    @pytest.mark.asyncio
    async def test_recent_event_with_claims(self):
        result = await QueryPreprocessor.preprocess_async(
            "What is the latest news on AI today?",
            "OpenAI released a new model called GPT-5. It performs better on reasoning tasks."
        )
        assert result.query_type == "recent_event"
        assert len(result.extracted_claims) > 0

    @pytest.mark.asyncio
    async def test_opinion_query(self):
        result = await QueryPreprocessor.preprocess_async(
            "Should I buy an iPhone or Android?",
            "It depends on your needs. iPhones are known for their ecosystem."
        )
        assert result.query_type == "opinion_subjective"
