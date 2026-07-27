"""
Wikipedia Retrieval - Layer 3A
Retrieves factual/encyclopedic information from Wikipedia API via async HTTPX.

Key async upgrade (Task 1):
- Accepts a shared httpx.AsyncClient (injected from app.state) so connections
  are pooled across requests rather than torn down and rebuilt every time.
- All fallback search terms are now fired CONCURRENTLY via asyncio.gather
  instead of the old sequential for-loop, turning O(N * 2 HTTP calls) wall
  time into O(1 * 2 HTTP calls) wall time for the parallel batch.
"""

import re
import asyncio
import httpx
from typing import Optional
from app.core.logging import get_logger
from app.core.cache import get_cached, set_cached

logger = get_logger(__name__)


class WikipediaRetriever:
    """
    Retrieves evidence from Wikipedia for encyclopedic claims.

    Accepts an optional shared httpx.AsyncClient. When one is provided (the
    production path), connections are reused via pooling. When none is provided
    (tests / standalone use), a short-lived client is created per call.
    """

    BASE_URL = "https://en.wikipedia.org/w/api.php"
    # Per-request read deadline — passed to the shared client at creation time
    # so this value is kept for documentation/reference only.
    TIMEOUT = 10.0

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        """
        Initialise Wikipedia retriever.

        Args:
            http_client: Optional shared AsyncClient from app.state.
                         Pass None to fall back to creating a per-call client
                         (useful for isolated unit tests).
        """
        self._shared_client = http_client

    # ── Private helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_search_terms(query: str) -> list[str]:
        """
        Extract search terms (Primary exact term -> Broader fuzzy keywords).
        """
        terms = []
        STOP_WORDS = {"The", "This", "That", "These", "Those", "Its", "His",
                       "Her", "Our", "Their", "Was", "Were", "Has", "Had",
                       "Are", "Not", "And", "But", "For", "With", "In"}

        # 1. Primary: exact phrase stripping punctuation
        clean_query = re.sub(r'[^\w\s]', '', query).strip()
        if clean_query:
            terms.append(clean_query)

        # 2. Extract multi-word entities (Fuzzy Keyword search)
        entities = re.findall(
            r'(?:\d{4}\s+)?(?:[A-Z][a-zA-Z]*\s+)*[A-Z][a-zA-Z]*', query
        )
        for entity in entities:
            entity = entity.strip()
            if entity not in terms and len(entity) > 2 and entity not in STOP_WORDS:
                terms.append(entity)

        # 3. Last resort fuzzy keyword: Capitalized proper nouns
        capitalized = re.findall(r'\b[A-Z][a-z]+\b', query)
        for term in capitalized:
            if term not in terms and len(term) > 2 and term not in STOP_WORDS:
                terms.append(term)

        # Make sure we have something
        if not terms:
            terms = [clean_query]

        return terms

    def _extract_top_snippets(self, text: str, query: str, top_n: int = 5) -> str:
        """
        Slice evidence to Top N snippets/sentences ranked by relevance.
        Returns more context so the LLM judge can make accurate decisions.
        """
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 15]

        if not sentences:
            return ""

        # Score sentences by keyword overlap with query
        query_words = set(query.lower().split())
        scored = []
        for s in sentences:
            s_lower = s.lower()
            score = sum(1 for w in query_words if w in s_lower)
            scored.append((score, s))

        # Sort by score desc, take top N
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [s[1] for s in scored[:top_n]]
        return " ... ".join(top)

    async def _fetch_term(
        self, client: httpx.AsyncClient, term: str, query: str
    ) -> Optional[dict]:
        """
        Attempt a full Wikipedia search + extract fetch for ONE term.

        This is the unit of work that gets fanned out concurrently by
        _search_with_client. Each term independently performs:
          1. Wikipedia search API  →  resolve page title
          2. Wikipedia extract API →  fetch article text

        Returns a result dict on success, or None on miss/error so the
        caller can pick the first non-None result from all parallel attempts.

        Args:
            client:  The httpx.AsyncClient to use for both HTTP calls.
            term:    The search term to query Wikipedia with.
            query:   The original user query (used for snippet ranking).

        Returns:
            dict with keys (title, content, url, found=True) or None.
        """
        try:
            # ── Step 1: Resolve page title via Wikipedia search API ───────────
            search_params = {
                "action": "query",
                "list": "search",
                "srsearch": term,
                "utf8": "",
                "format": "json",
                "srlimit": 1,
            }
            search_res = await client.get(self.BASE_URL, params=search_params)
            search_data = search_res.json()

            search_list = search_data.get("query", {}).get("search", [])
            if not search_list:
                logger.info(f"Wiki fuzzy miss for term: {term}")
                return None

            title = search_list[0]["title"]

            # ── Step 2: Fetch the page extract ───────────────────────────────
            extract_params = {
                "action": "query",
                "prop": "extracts",
                "exchars": 2000,
                "titles": title,
                "explaintext": 1,
                "format": "json",
            }
            ext_res = await client.get(self.BASE_URL, params=extract_params)
            ext_data = ext_res.json()

            pages = ext_data.get("query", {}).get("pages", {})
            if not pages or "-1" in pages:
                return None

            page_id = list(pages.keys())[0]
            content = pages[page_id].get("extract", "")

            if not content:
                return None

            # Extract top 5 most-relevant snippets for rich evidence
            snippets = self._extract_top_snippets(content, query, top_n=5)
            if not snippets:
                snippets = content[:600]  # fallback — more chars

            return {
                "title": title,
                "content": snippets,
                "url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                "found": True,
            }

        except httpx.TimeoutException:
            logger.error(f"Wiki timeout (>10s) for term: '{term}'")
            return None
        except Exception as e:
            logger.error(f"Wiki API error for term '{term}': {e}")
            return None

    async def _search_with_client(
        self, client: httpx.AsyncClient, query: str
    ) -> dict:
        """
        Core search logic using the provided client.

        Fires all fallback terms CONCURRENTLY via asyncio.gather, then
        returns the first successful result. This collapses what used to be
        O(N * 2) sequential HTTP calls into O(1 * 2) wall time.

        Args:
            client: The httpx.AsyncClient to use.
            query:  The user's claim/query string.

        Returns:
            dict with keys (title, content, url, found).
        """
        search_terms = self._extract_search_terms(query)
        logger.info(
            f"Wiki parallel search: {len(search_terms)} terms concurrently "
            f"→ {search_terms}"
        )

        # Fan out all terms simultaneously — each _fetch_term is independent
        raw_results = await asyncio.gather(
            *[self._fetch_term(client, term, query) for term in search_terms],
            return_exceptions=True,  # Prevent one failure from killing the batch
        )

        # Pick the first successful result (preserves original term priority order)
        for r in raw_results:
            if isinstance(r, Exception):
                logger.error(f"Wiki gather caught exception: {r}")
                continue
            if r is not None and r.get("found"):
                logger.info(f"Wiki Hit: '{r['title']}'")
                return r

        # Nothing found across all terms
        return {"title": None, "content": None, "url": None, "found": False}

    # ── Public API ───────────────────────────────────────────────────────────

    async def search(self, query: str) -> dict:
        """
        Search Wikipedia for a claim.

        Uses the shared client when available (production path with pooling),
        otherwise falls back to a short-lived per-call client (test path).

        Cache check runs before any HTTP is attempted.
        """
        cache_key = f"wiki_{query}"
        cached = await get_cached(cache_key)
        if cached:
            logger.info(f"Wiki cache hit for: {query}")
            return cached

        if self._shared_client is not None:
            # ── Production path: reuse pooled connections ─────────────────────
            result = await self._search_with_client(self._shared_client, query)
        else:
            # ── Fallback path: create a short-lived client (tests / standalone)
            async with httpx.AsyncClient(
                timeout=self.TIMEOUT,
                headers={
                    "User-Agent": "AIHallucinationDetector/1.0",
                    "Accept": "application/json",
                },
            ) as client:
                result = await self._search_with_client(client, query)

        # Cache regardless of hit/miss so repeated identical queries are free
        await set_cached(cache_key, result)
        return result

    async def get_evidence(self, claim: str) -> Optional[str]:
        """Get evidence text for a claim."""
        result = await self.search(claim)
        if result.get("found"):
            return result.get("content")
        return None
