"""
FastAPI security dependencies — app/api/dependencies.py

Exposes a single injectable dependency:

    get_current_user
        Reads the Authorization: Bearer <token> header via FastAPI's HTTPBearer
        scheme, delegates verification to the JWTVerifier singleton on
        app.state, and returns the verified user_id (sub claim) string.

        Any ValueError raised by the verifier (expired, tampered, missing sub)
        is translated to an HTTP 401 so callers never leak internal errors.

Usage in a route::

    from app.api.dependencies import get_current_user

    @router.post("/api/verify")
    async def verify(
        ...,
        user_id: str = Depends(get_current_user),
    ): ...
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.logging import get_logger

logger = get_logger(__name__)

# HTTPBearer validates that the Authorization header is present and has the
# "Bearer" scheme.  auto_error=True means FastAPI returns 403 automatically
# when the header is missing entirely (before our code even runs).
_bearer_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """
    FastAPI dependency — extract and verify the incoming JWT bearer token.

    Reads the JWTVerifier singleton wired by the lifespan in main.py
    (``request.app.state.auth_verifier``) so there is zero per-request
    construction cost.

    Args:
        request:     The raw FastAPI request (provides access to app.state).
        credentials: Parsed ``Authorization: Bearer <token>`` header injected
                     by FastAPI's ``HTTPBearer`` scheme.

    Returns:
        The verified user ID string extracted from the JWT ``sub`` claim.

    Raises:
        HTTPException(401): If the token is expired, tampered, missing ``sub``,
                            or the verifier is not yet initialised on app.state.
    """
    verifier = getattr(request.app.state, "auth_verifier", None)
    if verifier is None:
        # Defensive guard: lifespan should always set this, but handle the edge
        # case (e.g. during testing without the full app startup).
        logger.error("auth_verifier not found on app.state — lifespan not running?")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service not initialised",
        )

    try:
        user_id = verifier.extract_user_id(credentials.credentials)
    except ValueError as exc:
        logger.warning(f"Token verification failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    logger.debug(f"Authenticated request — user_id={user_id!r}")
    return user_id


async def get_optional_user(
    request: Request,
) -> str | None:
    """
    FastAPI dependency — extract the user ID if a valid JWT bearer token is present.
    Does not raise 401/403 exceptions if the token is missing, expired, or invalid;
    simply returns None.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    token = parts[1]
    verifier = getattr(request.app.state, "auth_verifier", None)
    if verifier is None:
        return None

    try:
        user_id = verifier.extract_user_id(token)
        return user_id
    except Exception as exc:
        logger.debug(f"Optional token verification failed: {exc}")
        return None

