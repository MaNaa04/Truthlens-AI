"""
Shared HTTP Client Factory
Provides a single application-lifetime httpx.AsyncClient with connection
pooling so every request reuses existing TCP/TLS connections rather than
paying the handshake cost each time.

Usage:
    # In main.py lifespan:
    app.state.http_client = create_http_client()
    yield
    await app.state.http_client.aclose()

    # In any retriever:
    client = app.state.http_client  # injected at construction time
"""

import httpx

# ── Defaults shared by Wikipedia and SerpAPI ──────────────────────────────────
# Both targets are HTTPS JSON APIs with identical timeout requirements.
# User-Agent is required by Wikipedia's API policy; harmless to SerpAPI.

_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": "AIHallucinationDetector/1.0",
    "Accept": "application/json",
}

_DEFAULT_TIMEOUT = httpx.Timeout(
    connect=5.0,   # TCP/TLS handshake deadline
    read=10.0,     # Server response deadline (matches original 10s intent)
    write=5.0,     # Request body send deadline
    pool=1.0,      # Wait time to acquire a connection from the pool
)

_DEFAULT_LIMITS = httpx.Limits(
    max_connections=20,           # Max simultaneous open connections
    max_keepalive_connections=10, # Keep-alive pool size
    keepalive_expiry=30.0,        # Seconds before an idle connection is closed
)


def create_http_client() -> httpx.AsyncClient:
    """
    Create a new shared httpx.AsyncClient with connection pooling.

    Must be called once at application startup (FastAPI lifespan) and stored
    on app.state. Must be closed on shutdown via ``await client.aclose()``.

    Connection pooling means:
    - No TCP handshake on subsequent requests to the same host
    - Saves ~100-300ms per request under normal network conditions
    - Safe for concurrent use across multiple asyncio coroutines
    """
    return httpx.AsyncClient(
        timeout=_DEFAULT_TIMEOUT,
        limits=_DEFAULT_LIMITS,
        headers=_DEFAULT_HEADERS,
    )
