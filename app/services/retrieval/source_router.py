"""
Source Router - Layer 3C
Routes queries to appropriate retrievers based on query type using asyncio.gather.

Key async upgrade (Task 1):
- Accepts a shared httpx.AsyncClient and passes it down to each retriever so
  the entire retrieval layer uses a single pooled connection manager.
- asyncio.gather now uses return_exceptions=True so a single failing task
  cannot propagate an unhandled exception and silently cancel the entire batch.
  Exception objects are filtered out before results are recombined.
"""

import asyncio
import httpx
from typing import Optional
from app.core.logging import get_logger
from app.services.retrieval.wikipedia_retriever import WikipediaRetriever
from app.services.retrieval.serp_retriever import SerpAPIRetriever
from app.services.retrieval.scholar_retriever import ScholarRetriever
from app.services.retrieval.gov_retriever import GovRetriever
from app.services.retrieval.news_retriever import NewsRetriever
from app.services.retrieval.medical_retriever import MedicalRetriever
from app.services.retrieval.finance_retriever import FinanceRetriever

logger = get_logger(__name__)


class SourceRouter:
    """
    Routes queries to appropriate retrieval sources concurrently via asyncio.gather.

    Accepts an optional shared httpx.AsyncClient that is forwarded to all
    retrievers. Pass None to let each retriever create its own client (useful
    for tests or standalone use).
    """

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        """
        Initialise SourceRouter with retrievers.

        Args:
            http_client: Optional shared AsyncClient from app.state.
                         Forwarded to WikipediaRetriever and SerpAPIRetriever
                         so the entire retrieval layer shares one connection pool.
        """
        self.wikipedia = WikipediaRetriever(http_client=http_client)
        self.serpapi = SerpAPIRetriever(http_client=http_client)
        self.scholar = ScholarRetriever(http_client=http_client)
        self.gov = GovRetriever(http_client=http_client)
        self.news = NewsRetriever(http_client=http_client)
        self.medical = MedicalRetriever(http_client=http_client)
        self.finance = FinanceRetriever(http_client=http_client)

    # ── Routing rules ────────────────────────────────────────────────────────

    def get_sources_for_query_type(self, query_type: str) -> list[str]:
        """Determine which sources to query based on the classified query type."""
        routing_rules = {
            "encyclopedic": ["wikipedia", "serpapi", "scholar", "gov"],
            "recent_event": ["serpapi", "wikipedia", "gov", "scholar", "news"],
            "numeric_statistical": ["wikipedia", "serpapi", "gov", "scholar", "finance"],
            "opinion_subjective": [],  # Skip retrieval entirely
            "medical_health": ["medical", "scholar", "gov"],
            "finance": ["finance", "news", "serpapi"],
            "programming": ["serpapi", "wikipedia"]
        }
        return routing_rules.get(query_type, ["wikipedia"])

    # ── Retrieval ────────────────────────────────────────────────────────────

    async def _retrieve_from_source(
        self, source: str, claim: str
    ) -> tuple[str, Optional[str]]:
        """
        Retrieve evidence from a single source for a single claim.

        Returns a (source_name, evidence_text_or_None) tuple so the gather
        result can be recombined by source regardless of order.
        """
        try:
            if source == "wikipedia":
                evidence = await self.wikipedia.get_evidence(claim)
                return ("Wikipedia", evidence)
            elif source == "serpapi":
                evidence = await self.serpapi.get_evidence(claim)
                return ("SerpAPI", evidence)
            elif source == "scholar":
                evidence = await self.scholar.get_evidence(claim)
                return ("Scholar", evidence)
            elif source == "gov":
                evidence = await self.gov.get_evidence(claim)
                return ("GovSource", evidence)
            elif source == "news":
                evidence = await self.news.get_evidence(claim)
                return ("News", evidence)
            elif source == "medical":
                evidence = await self.medical.get_evidence(claim)
                return ("Medical", evidence)
            elif source == "finance":
                evidence = await self.finance.get_evidence(claim)
                return ("Finance", evidence)
            else:
                return (source, None)
        except Exception as e:
            logger.error(f"Retrieval from '{source}' failed for claim '{claim}': {e}")
            return (source, None)

    async def retrieve_evidence(
        self, claims: list[str], query_type: str
    ) -> dict:
        """
        Parallel-fetch evidence for all claims across all relevant sources.

        Fans out every (claim × source) combination simultaneously using
        asyncio.gather. For N claims and M sources this fires N*M tasks
        concurrently so total wall time ≈ max(individual task time).

        Uses return_exceptions=True so a single task raising an unexpected
        exception does not propagate up and cancel the sibling tasks.
        Exception objects are filtered out before results are recombined.

        Args:
            claims:     List of extracted claim strings to look up.
            query_type: Classified query type used to select sources.

        Returns:
            Dict mapping source name → concatenated evidence string.
            Empty dict if no claims, no sources, or all fetches failed.
        """
        sources = self.get_sources_for_query_type(query_type)
        if not claims or not sources:
            return {}

        logger.info(
            f"Parallel fetching: {len(claims)} claims × {len(sources)} sources "
            f"= {len(claims) * len(sources)} concurrent tasks"
        )

        # Build all (claim, source) task combinations
        tasks = [
            asyncio.create_task(self._retrieve_from_source(source, claim))
            for claim in claims
            for source in sources
        ]

        # Fire simultaneously — return_exceptions=True ensures one bad task
        # cannot silently abort the entire gather batch
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Recombine evidence, skipping any tasks that raised exceptions
        evidence_map: dict[str, list[str]] = {}
        for result in raw_results:
            if isinstance(result, Exception):
                logger.error(f"Gather caught unexpected task exception: {result}")
                continue
            source_name, evidence = result
            if evidence:
                evidence_map.setdefault(source_name, []).append(evidence)

        # Join per source into a single string ready for the aggregator
        return {
            source_name: "\n\n".join(evidence_list)
            for source_name, evidence_list in evidence_map.items()
        }
