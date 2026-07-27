"""
Analytics API Routes
Endpoints for the dashboard to fetch stats and history.
"""

from fastapi import APIRouter, Depends, Request
from app.services.analytics.tracker import AnalyticsTracker
from app.api.dependencies import get_optional_user
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/stats")
async def get_stats(request: Request, user_id: str | None = Depends(get_optional_user)):
    """Get aggregate verification statistics."""
    tracker = AnalyticsTracker()
    return await tracker.get_stats_async(request.app.state.db, user_id)


@router.get("/history")
async def get_history(request: Request, limit: int = 50, user_id: str | None = Depends(get_optional_user)):
    """Get recent verification history."""
    tracker = AnalyticsTracker()
    events = await tracker.get_events_async(request.app.state.db, user_id, limit=limit)
    return {"events": events, "total": len(events)}


@router.get("/preprocessing")
async def get_preprocessing_stats(request: Request, user_id: str | None = Depends(get_optional_user)):
    """Get preprocessing-specific analytics (query types, claim extraction, etc.)."""
    tracker = AnalyticsTracker()
    return await tracker.get_preprocessing_stats_async(request.app.state.db, user_id)


@router.get("/pipeline")
async def get_pipeline_stats(request: Request, user_id: str | None = Depends(get_optional_user)):
    """Get per-stage pipeline performance breakdown."""
    tracker = AnalyticsTracker()
    return await tracker.get_pipeline_stats_async(request.app.state.db, user_id)


@router.delete("/clear")
async def clear_analytics(request: Request, user_id: str | None = Depends(get_optional_user)):
    """Clear all analytics data (for testing)."""
    tracker = AnalyticsTracker()
    await tracker.clear_async(request.app.state.db, user_id)
    return {"status": "cleared"}
