"""
SlowAPI rate-limiter configuration — app/core/limiter.py

Design
------
SlowAPI wraps limits-based rate limiting for FastAPI.  The default key
function uses the client's remote IP address, which would bucket all users
behind a shared NAT (e.g. a corporate proxy or the Chrome Extension's host
machine) into one counter — unfair and easy to accidentally exhaust.

We override the key function to use the JWT ``sub`` claim (user_id) instead,
so each user's request quota is tracked independently regardless of IP.

The user_id is resolved via a two-step lookup:
  1. FastAPI's HTTPBearer has already parsed the Authorization header by the
     time SlowAPI's key function runs (it runs *before* the route handler).
  2. We pull the raw bearer token from ``request.headers`` and call
     ``request.app.state.auth_verifier.extract_user_id()`` directly.

Fallback:
  If the Authorization header is missing or malformed (e.g. on the /health
  endpoint which doesn't require auth), the key falls back to the client's
  remote IP so public endpoints still get IP-based protection.

Usage::

    # In main.py:
    from app.core.limiter import limiter
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # On a protected route:
    from app.core.limiter import limiter

    @router.post("/api/verify")
    @limiter.limit("20/minute")
    async def verify(request: Request, ...): ...
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.logging import get_logger

logger = get_logger(__name__)


def _user_id_key(request) -> str:
    """
    Rate-limit key function — resolves to the authenticated user's ID.

    SlowAPI passes the raw Starlette ``Request`` object here (before the
    FastAPI dependency injection layer runs), so we read the bearer token
    directly from the Authorization header and verify it via app.state.

    Falls back to the client IP for unauthenticated endpoints (e.g. /health).

    Args:
        request: The incoming Starlette Request.

    Returns:
        A string key unique to this user (``user:<user_id>``) or
        ``ip:<remote_addr>`` for unauthenticated requests.
    """
    auth_header: str | None = request.headers.get("Authorization", "")
    if auth_header and auth_header.lower().startswith("bearer "):
        raw_token = auth_header[len("Bearer "):].strip()
        verifier = getattr(request.app.state, "auth_verifier", None)
        if verifier is not None:
            try:
                user_id = verifier.extract_user_id(raw_token)
                return f"user:{user_id}"
            except ValueError:
                # Invalid / expired token — fall through to IP-based key.
                # The auth dependency will reject the request with 401 next.
                pass

    # Fallback: IP-based key for public endpoints or pre-auth failures
    ip = get_remote_address(request)
    return f"ip:{ip}"


# Module-level Limiter singleton — imported by main.py and route files.
# key_func is the user-scoped resolver above.
limiter = Limiter(key_func=_user_id_key, default_limits=[])
