"""
Tests for the Retrieval Engine (Layer 3).
All external API calls are mocked — no real network requests.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.services.retrieval.wikipedia_retriever import WikipediaRetriever
from app.services.retrieval.serp_retriever import SerpAPIRetriever
from app.services.retrieval.source_router import SourceRouter
from app.services.retrieval.evidence_aggregator import EvidenceAggregator


# ── 3A: Wikipedia Retriever Tests ──────────────────────────────────

class TestWikipediaRetriever:
    """Tests for WikipediaRetriever with mocked HTTPX calls."""

    def _make_search_response(self, title="Paris"):
        """Create a mock Wikipedia search API JSON response."""
        resp = MagicMock()
        resp.json.return_value = {
            "query": {"search": [{"title": title}]}
        }
        return resp

    def _make_extract_response(self, title="Paris", content="Paris is the capital of France."):
        """Create a mock Wikipedia extract API JSON response."""
        resp = MagicMock()
        resp.json.return_value = {
            "query": {"pages": {"12345": {"extract": content}}}
        }
        return resp

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_successful_search(self, mock_get):
        mock_response_search = MagicMock()
        mock_response_search.json.return_value = {
            "query": {
                "search": [{"title": "Paris"}]
            }
        }
        mock_response_extract = MagicMock()
        mock_response_extract.json.return_value = {
            "query": {
                "pages": {
                    "12345": {
                        "extract": "Paris is the capital of France.\nIt is located along the Seine River."
                    }
                }
            }
        }
        mock_get.side_effect = [mock_response_search, mock_response_extract]

    def _make_empty_search_response(self):
        resp = MagicMock()
        resp.json.return_value = {"query": {"search": []}}
        return resp

    @pytest.mark.asyncio
    @patch("app.services.retrieval.wikipedia_retriever.get_cached", return_value=None)
    @patch("app.services.retrieval.wikipedia_retriever.set_cached")
    async def test_successful_search(self, mock_set_cache, mock_get_cache):
        retriever = WikipediaRetriever()

        mock_client = AsyncMock()
        # First call = search, second call = extract
        mock_client.get.side_effect = [
            self._make_search_response("Paris"),
            self._make_extract_response("Paris", "Paris is the capital and largest city of France. It is located along the Seine River."),
        ]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.retrieval.wikipedia_retriever.httpx.AsyncClient", return_value=mock_client):
            result = await retriever.search("Paris")

        assert result["found"] is True
        assert result["title"] == "Paris"
        assert "Paris" in result["content"]
        assert result["url"] == "https://en.wikipedia.org/wiki/Paris"

    @pytest.mark.asyncio
    @patch("app.services.retrieval.wikipedia_retriever.get_cached", return_value=None)
    @patch("app.services.retrieval.wikipedia_retriever.set_cached")
    async def test_page_not_found(self, mock_set_cache, mock_get_cache):
        retriever = WikipediaRetriever()

        mock_client = AsyncMock()
        mock_client.get.return_value = self._make_empty_search_response()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.retrieval.wikipedia_retriever.httpx.AsyncClient", return_value=mock_client):
            result = await retriever.search("xyznonexistentpage123")

        assert result["found"] is False
        assert result["content"] is None

    @pytest.mark.asyncio
    @patch("app.services.retrieval.wikipedia_retriever.get_cached", return_value=None)
    @patch("app.services.retrieval.wikipedia_retriever.set_cached")
    async def test_api_error_handled(self, mock_set_cache, mock_get_cache):
        retriever = WikipediaRetriever()

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Network error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.retrieval.wikipedia_retriever.httpx.AsyncClient", return_value=mock_client):
            result = await retriever.search("Paris")

        assert result["found"] is False

    @pytest.mark.asyncio
    @patch("app.services.retrieval.wikipedia_retriever.get_cached", return_value=None)
    @patch("app.services.retrieval.wikipedia_retriever.set_cached")
    async def test_get_evidence_returns_content(self, mock_set_cache, mock_get_cache):
        retriever = WikipediaRetriever()

        mock_client = AsyncMock()
        mock_client.get.side_effect = [
            self._make_search_response("Paris"),
            self._make_extract_response("Paris", "Paris is the capital of France. It has beautiful architecture."),
        ]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.retrieval.wikipedia_retriever.httpx.AsyncClient", return_value=mock_client):
            evidence = await retriever.get_evidence("Paris capital France")

        assert evidence is not None
        assert "Paris" in evidence

    @pytest.mark.asyncio
    @patch("httpx.AsyncClient.get")
    async def test_get_evidence_returns_none_when_not_found(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"query": {"search": []}}
        mock_get.return_value = mock_response

        retriever = WikipediaRetriever()
        evidence = await retriever.get_evidence("nonexistent claim")

    @patch("app.services.retrieval.wikipedia_retriever.get_cached", return_value=None)
    @patch("app.services.retrieval.wikipedia_retriever.set_cached")
    async def test_get_evidence_returns_none_when_not_found(self, mock_set_cache, mock_get_cache):
        retriever = WikipediaRetriever()

        mock_client = AsyncMock()
        mock_client.get.return_value = self._make_empty_search_response()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.retrieval.wikipedia_retriever.httpx.AsyncClient", return_value=mock_client):
            evidence = await retriever.get_evidence("nonexistent claim")

        assert evidence is None


# ── 3B: SerpAPI Retriever Tests ────────────────────────────────────

class TestSerpAPIRetriever:
    """Tests for SerpAPIRetriever with mocked serpapi."""

    @pytest.mark.asyncio
    @patch("app.services.retrieval.serp_retriever.get_settings")
    async def test_no_api_key_skips(self, mock_settings):
        mock_settings.return_value = MagicMock(serpapi_key="")
        retriever = SerpAPIRetriever()
        result = await retriever.search("test query")

        assert result["found"] is False
        assert result["results"] == []

    @pytest.mark.asyncio
    @patch("app.services.retrieval.serp_retriever.get_settings")
    async def test_placeholder_api_key_skips(self, mock_settings):
        mock_settings.return_value = MagicMock(serpapi_key="your_serpapi_key_here")
        retriever = SerpAPIRetriever()
        result = await retriever.search("test query")

        assert result["found"] is False

    @pytest.mark.asyncio
    @patch("app.services.retrieval.serp_retriever.get_settings")
    async def test_get_evidence_no_key(self, mock_settings):
        mock_settings.return_value = MagicMock(serpapi_key="")
        retriever = SerpAPIRetriever()
        evidence = await retriever.get_evidence("some claim")

        assert evidence is None


# ── 3C: Source Router Tests ────────────────────────────────────────

class TestSourceRouter:
    """Tests for SourceRouter routing logic."""

    def test_encyclopedic_routes_to_both(self):
        router = SourceRouter()
        sources = router.get_sources_for_query_type("encyclopedic")
        assert "wikipedia" in sources

    def test_recent_event_routes_to_both(self):
        router = SourceRouter()
        sources = router.get_sources_for_query_type("recent_event")
        assert "serpapi" in sources
        assert "wikipedia" in sources

    def test_numeric_routes_to_both(self):
        router = SourceRouter()
        sources = router.get_sources_for_query_type("numeric_statistical")
        assert "wikipedia" in sources
        assert "serpapi" in sources

    def test_opinion_skips_retrieval(self):
        router = SourceRouter()
        sources = router.get_sources_for_query_type("opinion_subjective")
        assert sources == []

    @pytest.mark.asyncio
    async def test_retrieve_evidence_no_claims(self):
        router = SourceRouter()
        result = await router.retrieve_evidence([], "encyclopedic")
        assert result == {}

    @pytest.mark.asyncio
    async def test_retrieve_evidence_opinion_returns_empty(self):
        router = SourceRouter()
        result = await router.retrieve_evidence(["some claim"], "opinion_subjective")
        assert result == {}

    @pytest.mark.asyncio
    @patch.object(WikipediaRetriever, "get_evidence", new_callable=AsyncMock, return_value="Paris is the capital of France.")
    async def test_retrieve_evidence_wikipedia_success(self, mock_wiki):
        router = SourceRouter()
        result = await router.retrieve_evidence(["Paris capital"], "encyclopedic")

        assert "Wikipedia" in result
        assert "Paris" in result["Wikipedia"]

    @pytest.mark.asyncio
    @patch.object(WikipediaRetriever, "get_evidence", new_callable=AsyncMock, side_effect=Exception("API down"))
    async def test_retrieve_evidence_handles_failure(self, mock_wiki):
        """When a retriever fails, it should not crash the whole pipeline."""
        router = SourceRouter()
        result = await router.retrieve_evidence(["some claim"], "encyclopedic")

        # Should return empty, not crash
        assert isinstance(result, dict)


# ── 3D: Evidence Aggregator Tests ──────────────────────────────────

class TestEvidenceAggregator:
    """Tests for EvidenceAggregator."""

    def test_deduplicate_exact(self):
        agg = EvidenceAggregator()
        evidence = ["Fact A", "Fact B", "Fact A", "Fact C"]
        result = agg.deduplicate(evidence)
        assert len(result) == 3
        assert "Fact A" in result

    def test_deduplicate_substring(self):
        agg = EvidenceAggregator()
        evidence = [
            "Paris is the capital of France and its largest city.",
            "Paris is the capital of France.",
        ]
        result = agg.deduplicate(evidence)
        # The shorter one is contained in the longer one, so drop the shorter
        assert len(result) == 1
        assert "largest city" in result[0]

    def test_deduplicate_empty(self):
        agg = MagicMock()
        agg.deduplicate = EvidenceAggregator.deduplicate
        assert EvidenceAggregator().deduplicate([]) == []

    def test_rank_evidence_prefers_medium_length(self):
        agg = EvidenceAggregator()
        short = "Short."
        medium = "This is a medium-length evidence snippet with some factual content about 42 things."
        long = "x" * 1200
        result = agg.rank_evidence([short, long, medium])
        # Medium should come first
        assert result[0] == medium

    def test_rank_evidence_penalizes_boilerplate(self):
        agg = EvidenceAggregator()
        good = "Paris has a population of over 2 million people."
        bad = "Click here to read more about our privacy policy and subscribe."
        result = agg.rank_evidence([bad, good])
        assert result[0] == good

    def test_trim_within_budget(self):
        agg = EvidenceAggregator()
        short_text = "This is short evidence."
        result = agg.trim_to_budget(short_text)
        assert result == short_text

    def test_trim_exceeds_budget(self):
        agg = EvidenceAggregator()
        # max_evidence_tokens from config is 2000, so budget = 2000 * 4 = 8000 chars
        char_budget = agg.max_tokens * 4
        long_text = "This is a sentence. " * 500  # ~10000 chars, well over budget
        result = agg.trim_to_budget(long_text)
        assert len(result) <= char_budget

    def test_aggregate_full_pipeline(self):
        agg = EvidenceAggregator()
        evidence = [
            "Paris is the capital of France.",
            "Paris is the capital of France.",  # duplicate
            "It has a population of over 2 million.",
        ]
        result = agg.aggregate(evidence)
        assert "Paris" in result
        assert len(result) > 0

    def test_aggregate_empty(self):
        agg = EvidenceAggregator()
        assert agg.aggregate([]) == ""
