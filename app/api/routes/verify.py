"""
Main Verify Route - Layer 1
API Gateway endpoint for hallucination detection.
POST /verify - Entry point for verification requests.

Async upgrades (Task 1 + Task 2):
- SourceRouter, LLMJudge, and EvidenceAggregator are singletons on app.state.
- Full verify result is cached in Redis (key = SHA-256 of question+answer).
  Cache hit short-circuits the entire pipeline and returns in <5ms.

Security upgrades (Task 2):
- JWT bearer authentication via get_current_user dependency (HTTPBearer).
- User-scoped rate limiting: 20 requests/minute per user_id (not per IP).
- History records written asynchronously via BackgroundTasks so the API
  response is returned immediately without blocking on MongoDB I/O.

IMPORTANT — Redis cache key contract:
  The verify cache key is ``verify_{SHA-256(question + answer)}``.
  It is intentionally GLOBAL across all users to maximise cache-hit rates.
  user_id is NOT injected into this key.
"""

import time
import uuid
import hashlib
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from app.api.dependencies import get_current_user
from app.core.limiter import limiter
from app.core.logging import get_logger
from app.core.cache import get_cached, set_cached
from app.db.mongo import UserHistoryRepository
from app.models.history import UserHistoryRecord
from app.models.request import VerifyRequest
from app.models.response import VerifyResponse, JudgeResponse, ClaimResult
from app.services.preprocessing.query_preprocessor import QueryPreprocessor
from app.services.analytics.tracker import AnalyticsTracker, VerificationEvent

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["verification"])

# ── Claim-aware cache TTLs ────────────────────────────────────────────────────
# Different query types have different shelf lives. A fact about Einstein is
# stable for years; a claim about today's stock price expires in minutes.
_QUERY_TYPE_TTL: dict[str, int] = {
    "encyclopedic":        604800,  # 7 days  — historical/stable facts
    "numeric_statistical": 86400,   # 24 hours — stats updated daily/weekly
    "recent_event":        3600,    # 1 hour  — news and current events
    "opinion_subjective":  1800,    # 30 min  — subjective, low cache value
}
_DEFAULT_VERIFY_TTL: int = 3600    # 1 hour fallback for unknown query types


# ── Constants ─────────────────────────────────────────────────────────────────
_MAX_QUESTION_LOG_CHARS = 1000  # Truncate question before passing to background task

# ── Background task: async history persistence ────────────────────────────────

async def _write_history(
    db,
    user_id: str,
    request_id: str,
    question: str,
    score: int,
    verdict: str,
    cache_hit: bool,
) -> None:
    """
    Persist a single UserHistoryRecord to MongoDB.

    Executed by FastAPI's BackgroundTasks *after* the response has been sent
    to the client, so the API latency is not affected by DB write time.

    Silently swallows all exceptions — a failed history write must never
    surface as an API error (the pipeline result was already returned).

    Args:
        db:         AsyncIOMotorDatabase handle from app.state.db.
        user_id:    JWT sub claim — the record's owner.
        request_id: UUID string from the pipeline VerifyResponse.
        question:   Original question text.
        score:      Hallucination risk score (0-100).
        verdict:    User-facing verdict string.
        cache_hit:  Whether the result was served from the global Redis cache.
    """
    if db is None:
        logger.debug("MongoDB not available — skipping history write")
        return
    try:
        record = UserHistoryRecord(
            user_id=user_id,
            request_id=uuid.UUID(request_id),
            question=question,
            score=score,
            verdict=verdict,
            cache_hit=cache_hit,
            timestamp=datetime.now(timezone.utc),
        )
        repo = UserHistoryRepository(db)
        inserted_id = await repo.insert(record.to_mongo_doc())
        logger.debug(
            f"History record saved — user={user_id!r} request_id={request_id} "
            f"_id={inserted_id}"
        )
    except Exception as exc:
        # Non-fatal: log and continue.  The client already received their response.
        logger.warning(f"History write failed (non-fatal): {exc}")


# ── Main verify endpoint ───────────────────────────────────────────────────────

@router.post("/verify", response_model=VerifyResponse)
@limiter.limit("20/minute")
async def verify(
    request: Request,
    body: VerifyRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user),
) -> VerifyResponse:
    """
    Verify if an AI answer contains hallucinations.
    Accuracy-first pipeline: may take 10-15 seconds for thorough verification.

    Requires:
        Authorization: Bearer <jwt-token> header.
        Rate limit: 20 requests per minute per user (HTTP 429 when exceeded).

    Singletons (source_router, judge, aggregator) are pulled from app.state
    to avoid per-request construction overhead and to share the pooled
    httpx.AsyncClient across all concurrent verify calls.

    After the response is built, a BackgroundTask asynchronously writes the
    result to MongoDB so the client receives the answer without any DB latency.
    """
    request_id = str(uuid.uuid4())
    pipeline_start = time.perf_counter()

    logger.info(
        f"[{request_id}] Verification request received | "
        f"user={user_id!r} "
        f"question_len={len(body.question)} answer_len={len(body.answer)}"
    )

    # ── Layer 0 — Full-pipeline cache check ──────────────────────────────────
    # Key = SHA-256(question + answer) — deterministic, collision-resistant.
    # GLOBAL across all users — user_id is intentionally NOT included here.
    # A cache hit short-circuits all 4 layers and returns in <5ms.
    _raw_verify_key = (
        hashlib.sha256(
            (body.question + body.answer).encode("utf-8")
        ).hexdigest()
    )
    verify_cache_key = f"verify_{_raw_verify_key}"

    cached_response = await get_cached(verify_cache_key)
    if cached_response is not None:
        logger.info(f"[{request_id}] Cache HIT — returning cached result")
        # Override cache_hit=True — the stored dict has False from when it was
        # first computed. We flip it here so Dev 4 can identify cached results.
        cached_response["cache_hit"] = True
        final_response = VerifyResponse(**cached_response)

        # Still write history for cache hits — the user's audit trail should
        # record every request they made, cached or not.
        if request.app.state.db is not None:
            background_tasks.add_task(
                _write_history,
                db=request.app.state.db,
                user_id=user_id,
                request_id=request_id,
                question=body.question[:_MAX_QUESTION_LOG_CHARS],
                score=final_response.score,
                verdict=final_response.verdict,
                cache_hit=True,
            )
        else:
            logger.warning(
                f"[{request_id}] Pipeline OK but history logging skipped — "
                f"MongoDB is unavailable"
            )
        return final_response

    # ── Pull singletons from app.state ────────────────────────────────────────
    source_router = request.app.state.source_router
    judge = request.app.state.judge
    aggregator = request.app.state.aggregator

    # ── Layer 2 — Query Preprocessing (Full LLM Triplet Extraction) ──────────
    step_start = time.perf_counter()
    preprocessing_ms = 0
    try:
        # Always use the full LLM-based preprocessing for accurate claim extraction.
        # The regex fast-path was bypassing LLM triplet extraction and producing
        # weak entity strings that failed to retrieve meaningful evidence.
        processed = await QueryPreprocessor.preprocess_async(body.question, body.answer)
        preprocessing_ms = int((time.perf_counter() - step_start) * 1000)
        logger.info(
            f"[{request_id}] Preprocess complete ({preprocessing_ms}ms) | "
            f"claims={len(processed.extracted_claims)}"
        )
    except Exception as e:
        preprocessing_ms = int((time.perf_counter() - step_start) * 1000)
        logger.error(f"[{request_id}] Preprocessing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query preprocessing failed: {str(e)}")

    # ── Layer 3 — Evidence Retrieval (Parallel via singleton SourceRouter) ───
    evidence_map = {}
    step_start = time.perf_counter()
    retrieval_ms = 0
    try:
        # Singleton router shares the pooled http client — no new client per request
        evidence_map = await source_router.retrieve_evidence(
            processed.extracted_claims,
            processed.query_type,
        )
        retrieval_ms = int((time.perf_counter() - step_start) * 1000)
        logger.info(
            f"[{request_id}] Retrieval complete ({retrieval_ms}ms) | "
            f"sources={len(evidence_map)}"
        )
    except Exception as e:
        retrieval_ms = int((time.perf_counter() - step_start) * 1000)
        logger.warning(
            f"[{request_id}] Retrieval failed, continuing empty: {e}", exc_info=True
        )
        evidence_map = {}

    # ── Layer 3 — Evidence Aggregation ───────────────────────────────────────
    aggregated_evidence = ""
    source_confidence = 1.0
    try:
        evidence_list = list(evidence_map.values()) if evidence_map else []
        aggregated_evidence = aggregator.aggregate(evidence_list)
        
        # ── Layer 3b — Consensus Check ───────────────────────────────────────
        # Only run mediator when multiple sources returned evidence
        if len(evidence_map) > 1:
            mediator = request.app.state.mediator
            consensus_result = await mediator.check_consensus(
                claims=processed.extracted_claims,
                evidence_map=evidence_map,
            )
            # Use adjusted evidence that contains mediator conflict info
            aggregated_evidence = consensus_result.adjusted_evidence
            source_confidence = consensus_result.confidence
            
    except Exception as e:
        logger.warning(f"[{request_id}] Aggregation/Mediation failed: {e}")
        aggregated_evidence = ""

    # ── Layer 4 — LLM Judge ──────────────────────────────────────────────────
    step_start = time.perf_counter()
    judge_ms = 0
    _judge_failed = False  # Track error fallback so we don't cache stale verdicts
    try:
        judge_response = await judge.judge(
            body.question,
            body.answer,
            aggregated_evidence,
        )
        judge_ms = int((time.perf_counter() - step_start) * 1000)
        logger.info(
            f"[{request_id}] Judge complete ({judge_ms}ms) | "
            f"score={judge_response.score} verdict={judge_response.verdict}"
        )
    except Exception as e:
        judge_ms = int((time.perf_counter() - step_start) * 1000)
        _judge_failed = True
        logger.error(
            f"[{request_id}] LLM judge failed ({judge_ms}ms), "
            f"returning neutral verdict: {e}",
            exc_info=True,
        )
        judge_response = JudgeResponse(
            score=50,
            verdict="unverifiable",
            explanation="Verification could not be completed due to service error.",
            flag=False,
        )
    
    # ── Layer 4b — Per-Claim Fine-Grained Scoring ─────────────────────────────
    claim_results = None
    try:
        if processed.extracted_claims:
            raw_claim_results = await judge.judge_per_claim(
                body.question,
                body.answer,
                aggregated_evidence,
                processed.extracted_claims,
            )
            if raw_claim_results:
                claim_results = [
                    ClaimResult(**cr) for cr in raw_claim_results
                ]
                logger.info(
                    f"[{request_id}] Per-claim scoring complete | "
                    f"claims_scored={len(claim_results)}"
                )
    except Exception as e:
        logger.warning(f"[{request_id}] Per-claim scoring failed (non-fatal): {e}")
        claim_results = None

    # ── Layer 5 — Response Building ────────────────────────────────
    processing_time_ms = int((time.perf_counter() - pipeline_start) * 1000)
    sources = list(evidence_map.keys()) if evidence_map else None

    debug_info = {
        "claims_extracted": processed.extracted_claims,
        "evidence_found": bool(aggregated_evidence),
        "evidence_snippets": evidence_map,
        "query_type": processed.query_type,
        "timing": {
            "preprocessing_ms": preprocessing_ms,
            "retrieval_ms": retrieval_ms,
            "judge_ms": judge_ms,
            "total_ms": processing_time_ms,
        },
    }
    
    # Extract provider/model info for benchmarking
    judge_provider = getattr(judge, 'provider', None)
    judge_model = getattr(judge, 'model', None)
    # Ensure these are strings (getattr on MagicMock returns mock objects)
    if judge_provider and not isinstance(judge_provider, str):
        judge_provider = None
    if judge_model and not isinstance(judge_model, str):
        judge_model = None

    final_response = VerifyResponse.from_judge_response(
        judge_resp=judge_response,
        sources=sources,
        request_id=request_id,
        processing_time_ms=processing_time_ms,
        debug=debug_info,
        claim_results=claim_results,
        provider=judge_provider,
        model=judge_model,
    )

    # ── Layer 5b — Cache the completed result ─────────────────────────────────
    # TTL is claim-aware:
    #   - Error fallbacks     → 60s   (self-evict quickly so next call retries)
    #   - recent_event        → 1h    (news changes fast)
    #   - encyclopedic        → 7d    (stable historical facts)
    #   - numeric_statistical → 24h   (stats update daily)
    #   - opinion_subjective  → 30min (low cache value)
    #   - unknown             → 1h    (safe default)
    try:
        if _judge_failed:
            cache_ttl = 60
        else:
            cache_ttl = _QUERY_TYPE_TTL.get(processed.query_type, _DEFAULT_VERIFY_TTL)

        # Skip full-TTL cache for very low-confidence consensus results
        min_score_to_cache = 0.5  # scores below this = too uncertain to freeze for days
        if not _judge_failed and source_confidence < min_score_to_cache:
            cache_ttl = 3600  # Still cache but with a short TTL so it retries soon
            logger.info(f"[{request_id}] Low source confidence ({source_confidence:.2f}), limiting cache TTL to 3600s")

        await set_cached(verify_cache_key, final_response.model_dump(), ttl=cache_ttl)

        if _judge_failed:
            logger.debug(
                f"[{request_id}] Error fallback cached with 60s TTL (will self-evict)"
            )
        else:
            logger.info(
                f"[{request_id}] Result cached | "
                f"query_type={processed.query_type} ttl={cache_ttl}s"
            )
    except Exception as e:
        logger.warning(f"[{request_id}] Cache store failed (non-fatal): {e}")

    # ── Analytics Tracking ───────────────────────────────────────────────────
    if request.app.state.db is not None:
        try:
            tracker = AnalyticsTracker()
            event = VerificationEvent(
                request_id=request_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                question_preview=body.question[:80],
                answer_preview=body.answer[:120],
                score=final_response.score,
                verdict=final_response.verdict,
                sources_used=sources or [],
                processing_time_ms=processing_time_ms,
                claims_count=len(processed.extracted_claims),
                evidence_chars=len(aggregated_evidence),
                provider=getattr(judge, "provider", ""),
                query_type=processed.query_type,
                sentences_found=processed.sentences_found,
                factual_sentences=processed.factual_sentences,
                preprocessing_time_ms=preprocessing_ms,
                retrieval_time_ms=retrieval_ms,
                judge_time_ms=judge_ms,
            )
            background_tasks.add_task(
                tracker.record_async,
                db=request.app.state.db,
                event=event,
                user_id=user_id
            )
        except Exception as e:
            logger.warning(f"[{request_id}] Analytics tracking failed: {e}")
    else:
        logger.warning(
            f"[{request_id}] Pipeline OK but analytics tracking skipped — "
            f"MongoDB is unavailable"
        )

    # ── Background: persist per-user history to MongoDB ──────────────────────
    # This fires AFTER the response has been sent — zero latency impact.
    if request.app.state.db is not None:
        background_tasks.add_task(
            _write_history,
            db=request.app.state.db,
            user_id=user_id,
            request_id=request_id,
            question=body.question[:_MAX_QUESTION_LOG_CHARS],
            score=final_response.score,
            verdict=final_response.verdict,
            cache_hit=False,
        )
    else:
        logger.warning(
            f"[{request_id}] Pipeline OK but history logging skipped — "
            f"MongoDB is unavailable"
        )

    logger.info(
        f"[{request_id}] Verify pipeline complete ({processing_time_ms}ms) | "
        f"user={user_id!r} score={final_response.score} verdict={final_response.verdict}"
    )
    return final_response


@router.get("/history", response_model=list[UserHistoryRecord])
async def get_history(
    request: Request,
    skip: int = 0,
    limit: int = 10,
    user_id: str = Depends(get_current_user),
) -> list[UserHistoryRecord]:
    """
    Retrieve paginated audit history logs for the authenticated user.
    """
    db = request.app.state.db
    if db is None:
        logger.warning("History query failed — MongoDB is not available")
        raise HTTPException(
            status_code=503,
            detail="Database service not available",
        )
    
    repo = UserHistoryRepository(db)
    docs = await repo.list_for_user(user_id, skip=skip, limit=limit)
    
    records = []
    for doc in docs:
        try:
            records.append(UserHistoryRecord(**doc))
        except Exception as exc:
            logger.warning(f"Failed to parse database history document: {exc}")
            
    return records


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "hallucination-detection"}
