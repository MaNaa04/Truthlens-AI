"""
SerpAPI Retrieval - Layer 3B
Retrieves live web results via async HTTPX for sub-second latency.

Key async upgrade (Task 1):
- Accepts a shared httpx.AsyncClient (injected from app.state) so TCP/TLS
  connections to serpapi.com are reused across requests via pooling.
- The fallback term loop intentionally stays SEQUENTIAL here: each SerpAPI
  call costs an API credit, so we only fall through to the next term if the
  current one genuinely returns no results. Parallelising would burn N credits
  even when term 1 succeeds.
"""

import re
import httpx
from typing import Optional
from app.core.logging import get_logger
from app.core.config import get_settings
from app.core.cache import get_cached, set_cached

logger = get_logger(__name__)

_SERPAPI_URL = "https://serpapi.com/search"


class SerpAPIRetriever:
    """
    Retrieves evidence from Google Search via SerpAPI HTTP rest endpoint.
    Uses 10s timeouts for accuracy-first operation.

    Accepts an optional shared httpx.AsyncClient. When one is provided (the
    production path), connections are pooled. When none is provided
    (tests / standalone use), a short-lived client is created per call.
    """

    TIMEOUT = 10.0  # Accuracy-first: allow up to 10 seconds

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        """
        Initialise SerpAPI retriever.

        Args:
            http_client: Optional shared AsyncClient from app.state.
                         Pass None to fall back to creating a per-call client.
        """
        settings = get_settings()
        self.api_key = settings.serpapi_key
        self._shared_client = http_client

    # ── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _fuzzy_keywords(query: str) -> list[str]:
        """Generate broader search terms if the strict query fails."""
        terms = [query]
        # Drop all numbers/symbols and grab capitalized proper nouns
        capitalized = re.findall(r'\b[A-Z][a-z]+\b', query)
        if capitalized:
            terms.append(" ".join(capitalized))

        # Simple stopword strip
        stopwords = {"the", "is", "at", "which", "on"}
        clean = " ".join([w for w in query.split() if w.lower() not in stopwords])
        if clean and clean != query:
            terms.append(clean)

        return terms

    async def _search_with_client(
        self, client: httpx.AsyncClient, query: str
    ) -> dict:
        """
        Core SerpAPI search logic using the provided client.

        The fallback loop is kept SEQUENTIAL because each iteration costs an
        API credit. Only if the primary query returns no usable results do we
        try the next (broader) term — matching the original intent.

        Args:
            client: The httpx.AsyncClient to use.
            query:  The user's claim/query string.

        Returns:
            dict with keys (found, results, search_metadata).
        """
        search_terms = self._fuzzy_keywords(query)
        logger.info(f"Searching SerpAPI for: {query[:50]}...")

        for term in search_terms:
            try:
                params = {
                    "q": term,
                    "api_key": self.api_key,
                    "engine": "google",
                    "num": 2,  # Top 2 snippets ONLY
                }

                res = await client.get(_SERPAPI_URL, params=params)
                raw = res.json()
                results = []

                # Extract Knowledge Graph first
                if "answer_box" in raw:
                    box = raw["answer_box"]
                    answer = box.get("answer") or box.get("snippet") or box.get("result")
                    if answer:
                        results.append({
                            "title": box.get("title", "Answer Box"),
                            "snippet": str(answer),
                            "url": box.get("link", ""),
                            "source": "knowledge_graph",
                        })

                # Extract Top Organic — up to 5 results for richer evidence
                for item in raw.get("organic_results", [])[:5]:
                    if len(results) >= 5:
                        break
                    results.append({
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                        "url": item.get("link", ""),
                        "source": "organic",
                    })

                if results:
                    response_obj = {
                        "found": True,
                        "results": results,
                        "search_metadata": raw.get("search_metadata"),
                    }
                    logger.info(f"SerpAPI Hit: {len(results)} top snippets via '{term}'")
                    return response_obj

            except httpx.TimeoutException:
                logger.error(f"SerpAPI timeout (>10s) for: '{term}' — trying next term")
                continue  # Try remaining search terms instead of aborting
            except Exception as e:
                logger.error(f"SerpAPI search failed for term '{term}': {e}")
                continue

        return {"found": False, "results": [], "search_metadata": None}

    # ── Public API ───────────────────────────────────────────────────────────

    async def search(self, query: str) -> dict:
        """
        Search Google via SerpAPI for a claim.

        Uses the shared client when available (production path with pooling),
        otherwise falls back to a short-lived per-call client (test path).

        Cache check runs before any HTTP is attempted.
        """
        if not self.api_key or self.api_key == "your_serpapi_key_here":
            return {"found": False, "results": [], "search_metadata": None}

        cache_key = f"serp_{query}"
        cached = await get_cached(cache_key)
        if cached:
            logger.info(f"SerpAPI Cache hit for: {query}")
            return cached

        if self._shared_client is not None:
            # ── Production path: reuse pooled connections ─────────────────────
            result = await self._search_with_client(self._shared_client, query)
        else:
            # ── Fallback path: create a short-lived client (tests / standalone)
            async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                result = await self._search_with_client(client, query)

        # Cache regardless of hit/miss so repeated identical queries are free
        await set_cached(cache_key, result)
        return result

    async def get_evidence(self, claim: str) -> Optional[str]:
        """Get evidence from Top 5 web search snippets."""
        result = await self.search(claim)
        if result.get("found") and result.get("results"):
            snippets = [r.get("snippet", "") for r in result["results"] if r.get("snippet")]
            # Join up to top 5 for richer context
            return "\n".join(snippets[:5]) if snippets else None
        return None
