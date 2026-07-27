"""
Google OAuth2 authentication router — app/api/routes/auth.py

Flow:
  1. Chrome Extension calls chrome.identity.getAuthToken() → gets a Google access token.
  2. Extension sends that token to POST /api/auth/google-login.
  3. This endpoint verifies the token with Google's userinfo endpoint.
  4. It upserts the user record in MongoDB (stores only google_id + email).
  5. It mints a TruthLens JWT and returns it to the Extension.
  6. The Extension stores the JWT in chrome.storage.local for all future requests.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.core.auth import create_access_token
from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Google's endpoint to verify an OAuth2 access token and retrieve user info.
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


class GoogleLoginRequest(BaseModel):
    google_token: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str


@router.post(
    "/google-login",
    response_model=AuthResponse,
    summary="Exchange a Google OAuth2 token for a TruthLens JWT",
)
async def google_login(
    body: GoogleLoginRequest,
    request: Request,
) -> AuthResponse:
    """
    Verify a Google access token and issue a TruthLens JWT.

    Steps:
      1. Call Google's userinfo endpoint to validate the token and get the user's
         profile (google_id / sub, email).
      2. Upsert the user document in MongoDB (create on first login, update
         last_login_at on subsequent logins).
      3. Mint a TruthLens JWT signed with JWT_SECRET and return it.

    Args:
        body:    Request body containing the Google access token from the extension.
        request: FastAPI request (provides access to app.state).

    Returns:
        AuthResponse containing the TruthLens JWT and basic user info.

    Raises:
        HTTPException(401): If the Google token is invalid or expired.
        HTTPException(503): If the HTTP client is not initialised.
    """
    http_client = getattr(request.app.state, "http_client", None)
    if http_client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="HTTP client not initialised",
        )

    # ── Step 1: Verify with Google ─────────────────────────────────────────────
    try:
        resp = await http_client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {body.google_token}"},
            timeout=10.0,
        )
        resp.raise_for_status()
        user_info = resp.json()
    except Exception as exc:
        logger.warning(f"Google token verification failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Google token. Please sign in again.",
        ) from exc

    google_id: str = user_info.get("sub", "")
    email: str = user_info.get("email", "")

    if not google_id or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google did not return a valid user identity.",
        )

    logger.info(f"Google OAuth2 verified: email={email!r} google_id={google_id!r}")

    # ── Step 2: Upsert user in MongoDB ─────────────────────────────────────────
    db = getattr(request.app.state, "db", None)
    if db is not None:
        try:
            users_col = db["users"]
            now = datetime.now(timezone.utc)
            await users_col.update_one(
                {"google_id": google_id},
                {
                    "$set": {"email": email, "last_login_at": now},
                    "$setOnInsert": {"google_id": google_id, "created_at": now},
                },
                upsert=True,
            )
            logger.debug(f"User upserted in MongoDB: {email!r}")
        except Exception as exc:
            # Non-fatal: log but continue — history just won't be persisted.
            logger.error(f"MongoDB user upsert failed (non-fatal): {exc}")
    else:
        logger.warning("MongoDB unavailable — skipping user upsert")

    # ── Step 3: Mint TruthLens JWT ─────────────────────────────────────────────
    truthlens_token = create_access_token(
        sub=google_id,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        expires_seconds=settings.jwt_expiry_seconds,
    )

    return AuthResponse(
        access_token=truthlens_token,
        user_id=google_id,
        email=email,
    )
