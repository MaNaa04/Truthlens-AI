"""
Finance Retriever - Layer 3B
Retrieves evidence from financial domains (reuters, bloomberg, wsj) via SerpAPI
"""

import httpx
from typing import Optional
from app.core.logging import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)

_SERPAPI_URL = "https://serpapi.com/search"

class FinanceRetriever:
    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        settings = get_settings()
        self.api_key = settings.serpapi_key
        self._shared_client = http_client

    async def get_evidence(self, claim: str) -> Optional[str]:
        if not self.api_key:
            return None
            
        try:
            if self._shared_client:
                return await self._fetch(self._shared_client, claim)
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    return await self._fetch(client, claim)
        except Exception as e:
            logger.error(f"Finance retrieval failed for '{claim}': {e}")
            return None

    async def _fetch(self, client: httpx.AsyncClient, claim: str) -> Optional[str]:
        query = f"{claim} (site:reuters.com OR site:bloomberg.com OR site:wsj.com OR site:cnbc.com OR site:yahoofinance.com)"
        params = {
            "q": query,
            "api_key": self.api_key,
            "engine": "google",
            "num": 3,
        }
        res = await client.get(_SERPAPI_URL, params=params)
        raw = res.json()
        
        snippets = []
        if "organic_results" in raw:
            for r in raw["organic_results"]:
                if "snippet" in r:
                    snippets.append(r["snippet"])
                    
        return " | ".join(snippets) if snippets else None
