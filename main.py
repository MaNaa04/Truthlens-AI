"""Main FastAPI application entrypoint"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from contextlib import asynccontextmanager
import os
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.http_client import create_http_client
from app.core.cache import init_cache, close_cache
from app.core.auth import JWTVerifier
from app.core.limiter import limiter
from app.db.mongo import init_mongo, close_mongo
from app.api.routes.verify import router as verify_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.auth import router as auth_router

# Initialize logger
logger = get_logger(__name__)

# Load settings
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle events for the FastAPI application.

    Startup:
      - Creates a single shared httpx.AsyncClient with connection pooling.
        All retrievers in the pipeline share this one client, which means
        TCP/TLS connections to Wikipedia and SerpAPI are reused across
        requests instead of torn down and rebuilt on every call.
      - Instantiates SourceRouter, LLMJudge, and EvidenceAggregator once
        and stores them on app.state. The verify route pulls these singletons
        on every request rather than paying the constructor cost each time.

    Shutdown:
      - Cleanly closes the shared HTTP client, flushing pooled connections.
    """
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Debug mode: {settings.app_debug}")

    # ── Redis cache (must come first — retrievers use it immediately) ───────
    if settings.redis_enabled and settings.cache_enabled:
        await init_cache(
            redis_url=settings.redis_url,
            ttl_seconds=settings.cache_ttl_seconds,
        )
    else:
        logger.info("Redis disabled via config — using in-memory TTLCache only")

    # ── Shared HTTP client (connection pooling) ───────────────────────────────
    # Import here to avoid circular-import issues at module level
    from app.services.retrieval.source_router import SourceRouter
    from app.services.judge.llm_judge import LLMJudge
    from app.services.retrieval.evidence_aggregator import EvidenceAggregator
    from app.services.judge.grok_mediator import GrokMediator

    app.state.http_client = create_http_client()
    logger.info("Shared httpx.AsyncClient created (connection pooling enabled)")

    # ── Application-lifetime singletons ──────────────────────────────────────
    app.state.source_router = SourceRouter(http_client=app.state.http_client)
    logger.info("SourceRouter singleton initialised")

    app.state.judge = LLMJudge()
    logger.info(f"LLMJudge singleton initialised (model: {app.state.judge.model})")

    app.state.aggregator = EvidenceAggregator()
    logger.info("EvidenceAggregator singleton initialised")

    app.state.mediator = GrokMediator()
    logger.info("GrokMediator singleton initialised")

    # ── JWT Verifier (stateless; instantiated once, shared per request) ────────
    # Tokens are minted client-side (Chrome Extension → Supabase/Firebase).
    # We only verify signatures here — never mint tokens ourselves.
    app.state.auth_verifier = JWTVerifier(
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    logger.info(
        f"JWTVerifier singleton initialised (algorithm={settings.jwt_algorithm})"
    )

    # ── MongoDB async client (per-user history; decoupled from Redis) ────────
    # Redis cache keys stay GLOBAL (verify_{sha256}) for max hit rates.
    # Mongo is the per-user audit store; kept strictly separate.
    try:
        app.state.db = await init_mongo(
            mongodb_url=settings.mongodb_url,
            database_name=settings.database_name,
        )
        logger.info(
            f"MongoDB singleton initialised — db='{settings.database_name}'"
        )
    except Exception as exc:
        logger.warning(
            f"MongoDB unavailable at startup ({exc}). "
            "app.state.db will be None — history persistence is disabled."
        )
        app.state.db = None

    yield  # ── Application runs ──────────────────────────────────────────────

    # ── Shutdown: release pooled connections ─────────────────────────────────
    await app.state.http_client.aclose()
    logger.info("Shared httpx.AsyncClient closed")
    await close_cache()
    logger.info("Redis cache closed")
    if app.state.db is not None:
        await close_mongo(app.state.db)
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Backend for AI Hallucination Detection System",
    debug=settings.app_debug,
    lifespan=lifespan,
)

# Add CORS middleware for extension communication
# Origins controlled via ALLOWED_ORIGINS in .env (defaults to ["*"] for dev).
# When Dev 1 ships JWT auth, set: ALLOWED_ORIGINS=chrome-extension://<extension-id>
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate limiting (SlowAPI) ────────────────────────────────────────────────
# Bind the module-level limiter singleton to app.state so SlowAPIMiddleware
# can find it. The custom key_func (in app/core/limiter.py) resolves requests
# to user:<user_id> keys instead of client IP for per-user quotas.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# Include routers
app.include_router(auth_router)
app.include_router(verify_router)
app.include_router(analytics_router)

# Mount dashboard static files
dashboard_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard")
if os.path.exists(dashboard_dir):
    app.mount("/dashboard", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")

# Mount analytics dashboard
analytics_dashboard_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analytics-dashboard")
if os.path.exists(analytics_dashboard_dir):
    app.mount("/analytics", StaticFiles(directory=analytics_dashboard_dir, html=True), name="analytics-dashboard")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "dashboard": "/dashboard",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        reload=settings.app_debug,
    )
