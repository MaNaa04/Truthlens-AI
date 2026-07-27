# Development Notes & Architecture Details

## System Overview

### Problem Statement
AI language models generate confident but sometimes incorrect answers. This system detects hallucinations by:
1. Retrieving evidence from trusted sources
2. Grounding an LLM judge in that evidence
3. Returning a hallucination risk score to users

### Why Evidence-Grounded Judging?
- **Pure GPT-as-a-Judge Problem**: LLM judge itself can hallucinate
- **Solution**: Provide external evidence (Wikipedia, SerpAPI) to ground the judge
- **Benefit**: Reduces false positives and improves reliability

## Architecture Deep Dive

### Layer 1: API Gateway (verify.py)
```
Request: {"question": "...", "answer": "..."}
        ↓
   [JWT Auth Token Validation (get_current_user)]
        ↓
   [SlowAPI Rate Limiter (20 requests/minute)]
        ↓
   [Global Redis Cache Lookup (SHA-256(question + answer))]
     ├── (HIT) ─→ Return cached response & spawn background MongoDB user audit log
     └── (MISS)
        ↓
   [Coordinate Pipeline]
     Call Layer 2 → Layer 3 → Layer 4 → Layer 5
        ↓
   [Spawn Background MongoDB User Audit Log]
        ↓
Response: {"score": 0-100, "verdict": "...", ...}
```python
app = FastAPI(
    title="AI Hallucination Detection Backend",
    version="0.1.0",
    debug=settings.app_debug,
    lifespan=lifespan   # Async startup/shutdown lifecycle
)

# CORS restricted to production Chrome Extension ID
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, ...)

# Routers registered
app.include_router(auth_router)       # POST /api/auth/google-login
app.include_router(verify_router)     # POST /api/verify, GET /api/history, GET /api/health
app.include_router(analytics_router)  # GET /api/analytics

# Static dashboards
app.mount("/dashboard", StaticFiles(directory="dashboard"), name="dashboard")
app.mount("/analytics", StaticFiles(directory="analytics-dashboard"), name="analytics")
```

**CORS**: Locked down to `ALLOWED_ORIGINS=["chrome-extension://iffeaoceohaoncddifljbjjkgakpgmie"]` in `.env`. Requests from all other origins are rejected.

**Startup sequence** (via `asynccontextmanager lifespan`):
1. Init Redis cache (Upstash cloud)
2. Create shared `httpx.AsyncClient`
3. Init `SourceRouter`, `LLMJudge`, `EvidenceAggregator`, `GrokMediator` singletons
4. Init `JWTVerifier` singleton
5. Init MongoDB Atlas connection

**Run with**:
```bash
python main.py
```

**Key Responsibility**: JWT Security verification, user rate limiting, global caching lookup/storage, pipeline coordination, and asynchronous per-user audit logging.
**Testability**: Integration tests verify the end-to-end flow, caching mechanics, and auth/rate-limiting security gates.

### Layer 2: Query Preprocessor
```
Answer: "Paris is the capital of France"
        ↓
  [Claim Extraction]
        ↓
  - "Paris is capital of France"
  - "Location: France"
        ↓
  [Query Type Detection]
        ↓
  Type: "encyclopedic" → Route to Wikipedia
```

**Implementation Strategy**:
- **Option A (Simple)**: Regex-based claim extraction + keyword matching
  - Pros: Fast, no external dependencies
  - Cons: Less accurate on complex sentences
- **Option B (Better)**: Small LLM call to extract claims
  - Pros: More accurate claim extraction
  - Cons: Adds one API call per request
- **Recommendation**: Start with Option A, upgrade to B based on feedback

### Layer 3: Retrieval Engine (Most Complex)

#### Part A: Wikipedia Retriever
```
Claim: "Paris is capital of France"
        ↓
[Call Wikipedia API with search query]
        ↓
[Extract top 2 paragraphs from article]
        ↓
Evidence: "Paris is the capital and largest city of France..."
```

**Technical Details**:
- Implementation: Direct async `httpx` HTTP calls to the Wikipedia MediaWiki API
- Timeout: 10 second timeout per request for robustness
- Error handling: Return `{"found": False}` on failures
- Caching: Results cached in-memory to avoid duplicate lookups

#### Part B: SerpAPI Retriever
```
Claim: "New COVID variant discovered Jan 2024"
        ↓
[Call SerpAPI with Google search]
        ↓
[Extract top 3 search result snippets]
        ↓
Evidence: [Snippet 1, Snippet 2, Snippet 3]
```

**Cost Consideration**:
- SerpAPI costs ~$0.01-0.05 per call
- **Gate it**: Only call if Wikipedia lacks results OR query_type == "recent_event"

#### Part C: Source Router
```
Query Type Detection (from Layer 2)
        ↓
Routing Rules:
  - "encyclopedic" → Wikipedia only
  - "recent_event" → SerpAPI first, Wikipedia fallback
  - "numeric_statistical" → Both
  - "opinion_subjective" → Skip retrieval
        ↓
Selected Sources: []
```

**No LLM call here** - Just simple if/else logic

#### Part D: Evidence Aggregator
```
[Wikipedia snippet] + [SerpAPI results] + [Additional sources]
        ↓
[Step 1: Deduplicate]
  Remove exact duplicates and near-duplicates (fuzzy matching optional)
        ↓
[Step 2: Rank by Relevance]
  Wikipedia snippets ranked higher (more reliable)
  Shorter, clearer snippets prioritized
        ↓
[Step 3: Trim to Budget]
  Max 2000 tokens (~8000 chars) — configurable via MAX_EVIDENCE_TOKENS
  Keep important info, drop boilerplate
        ↓
Final Evidence (ready for judge)
```

**Token Estimation**:
- 1 token ≈ 4 characters (rough estimate)
- 2000 tokens ≈ 8000 characters (default budget)

### Layer 4: LLM Judge
```
System Prompt: [Fact-verification instructions]
User Input:
  QUESTION: {question}
  ANSWER: {answer}
  EVIDENCE: {evidence}
        ↓
   [LLM processes]
        ↓
JSON Response:
{
  "score": 85,
  "verdict": "verified",
  "explanation": "...",
  "flag": false
}
```

**Prompt Design Matters**:
- Emphasize using ONLY provided evidence
- Ask for specific JSON format
- Include score range (0-100) definition
- Request 1-2 sentence explanation

**Active Provider**: `groq` with `llama-3.3-70b-versatile` (free, fast, ~3s response).

**Supported LLM Providers** (all implemented):
- Groq: `llama-3.3-70b-versatile` ✅ **Active** (via OpenAI-compat endpoint)
- Google Gemini: `gemini-2.0-flash` (via OpenAI-compat endpoint)
- OpenAI: GPT-4, GPT-4o (requires paid billing)
- Grok (xAI): Via `https://api.x.ai/v1` OpenAI-compat endpoint
- Anthropic: Claude Sonnet/Haiku (via native `AsyncAnthropic` SDK)

> **Decommissioned**: `groq` + `llama3-70b-8192` — use `llama-3.3-70b-versatile` instead.

### Layer 5: Response Builder
```
Judge Output: {"score": 85, "verdict": "verified", ...}
        ↓
[Map to User-Friendly Verdict]
  75-100 → "accurate"
  40-74 → "uncertain"
  0-39 → "hallucination"
        ↓
Final Response:
{
  "score": 85,
  "verdict": "accurate",
  "explanation": "...",
  "flag": false,
  "sources_used": ["Wikipedia"]
}
```

## Key Design Decisions

### 1. Handling Unverifiable Claims
**Scenario**: Wikipedia and SerpAPI find no relevant evidence

**Decision**: Return neutral score (50) with "unverifiable" verdict
- More honest than treating lack of evidence as hallucination
- User can manually verify using other sources
- Alternative: Mark as risky (score 30), but this could be too aggressive

**Decision File**: `app/models/response.py`

### 2. Single vs. Per-Claim Scoring
**Both are now implemented**:
- **Global score**: Single 0–100 score for the entire answer (Layer 4)
- **Per-claim scores**: Each extracted claim gets its own score, verdict, and explanation (Layer 4b)
- Per-claim results include character-offset mapping (`start_index`, `end_index`) for highlighting
- Chrome Extension renders both: overall badge + expandable per-claim breakdown cards
- Per-claim scoring is non-blocking: if it fails, the response still returns with `claim_results: null`

### 3. Evidence Budget
**Decision**: ~2000 tokens max for judge input (configurable via `MAX_EVIDENCE_TOKENS`)
- Larger budget improves judge accuracy with richer context
- Prevents context window overflow
- Per-claim calls use `max_tokens=800` (vs 400 for single-claim) for larger JSON arrays

## Data Flow Through Full Pipeline

```
User Input (Extension/Postman)
        ↓
POST /verify {"question": "Q", "answer": "A"}
        ↓
[Layer 1] Input validation, route to pipeline
        ↓
[Layer 2] Extract claims, determine type
        ↓
[Layer 3A] Wikipedia search (if applicable)
[Layer 3B] SerpAPI search (if applicable)
[Layer 3C-D] Aggregate + trim evidence
        ↓
[Layer 4] Judge: "Q + A + Evidence → Score"
        ↓
[Layer 5] Format response
        ↓
Response to frontend/extension
        ↓
User sees: Score badge + Explanation
```

## Error Handling Strategy

### What Can Go Wrong?

1. **Input Validation Fails** → HTTP 422
2. **External API Down** (Wikipedia/SerpAPI)
   - Graceful degradation: Continue with partial evidence
   - Log the error, mark source as unavailable
3. **LLM API Timeout**
   - Return neutral score (50)
   - Log error with context
4. **Invalid JSON from Judge**
   - Parse error → Return generic response
   - Log raw response for debugging

### Implementation Pattern
```python
try:
    result = retrieve_evidence(claim)
except TimeoutError:
    logger.warning("Wikipedia timeout, continuing")
    result = {"found": False}
except Exception as e:
    logger.error(f"Unexpected error: {e}", exc_info=True)
    result = {"found": False}

# Continue pipeline, handle empty results gracefully
```

## Performance Optimization Opportunities

### 1. Caching (Low Hanging Fruit)
- Cache evidence retrieval by claim hash
- TTL: 1 hour (might change if configured)
- Backend: In-memory for dev, Redis for prod

### 2. Batch Processing
- Accept multiple Q&A pairs in single request
- Process in parallel
- Return batch results

### 3. Async I/O
- Wikipedia API calls can be concurrent
- SerpAPI calls can be concurrent
- But don't exceed rate limits

### 4. Smart Routing
- If answer length > 500 chars, extract multiple claims
- If query type is "opinion", skip retrieval entirely
- If score confidence high, skip SerpAPI (save $)

## Testing Strategy

### Automated Test Suite
The codebase includes 144 automated tests that cover unit functionality, error handling, security configurations, and full end-to-end routing.

- **Models (`tests/test_models.py`)**: 21 tests verifying Pydantic v2 schemas and validation constraints.
- **Preprocessing (`tests/test_preprocessor.py`)**: 24 tests validating factual claim filtering and query type detection.
- **Retrievers (`tests/test_retrievers.py`)**: 25 tests verifying Wikipedia search extraction, SerpAPI organic snippets, and smart source routing.
- **LLM Judge (`tests/test_judge.py`)**: 14 tests verifying system prompt composition, JSON parsing robustness, and heuristic overlap fallbacks.
- **Security Gates (`tests/test_security.py`)**: 21 tests validating JWT verification behavior, bearer scheme exceptions, and CORS whitelists.
- **History Logs (`tests/test_auth_history.py`)**: 29 tests validating database schemas, Motor async insertion, and paginated retrieval endpoints.
- **Full Pipeline (`tests/test_verify.py`)**: 10 integration tests mocking external APIs to verify orchestration, caching logic, and error resilience.

## Security Considerations

### 1. Google OAuth2 + TruthLens JWT Authentication
- The Chrome Extension uses `chrome.identity.launchWebAuthFlow` to allow users to select/switch Google accounts.
- After OAuth2 consent, the Extension POSTs the Google ID token to `POST /api/auth/google-login`.
- The backend verifies the Google token, upserts the user in MongoDB, and mints a TruthLens HS256 JWT (1-hour expiry).
- Every protected endpoint (except `/api/health` and `/api/auth/google-login`) requires `Authorization: Bearer <token>`.
- Token extraction and verification are handled by a startup-initialized `JWTVerifier` singleton (`app.state.auth_verifier`).
- The Extension auto-detects 401 responses, clears the stored token, and prompts re-sign-in (implemented in `content.js` and `ai-chat-injector.js`).

### 2. User-Scoped Rate Limiting
- Configured using SlowAPI to prevent abuse and denial-of-service.
- Rate limits (20 requests per minute) are keyed to the verified `user_id` extracted from the token's `sub` claim, rather than the client's IP address.

### 3. Production CORS Whitelist
- Allows whitelisting explicit browser extension origins (e.g. `chrome-extension://<extension-id>`) via the `ALLOWED_ORIGINS` environment variable.
- Rejects requests from unlisted external sites in production to lock down endpoints.

### 4. Database Isolation
- History logs are written per user, using the verified `user_id` as a partition.
- Caching remains global and anonymous (without storing user IDs in Redis) to respect privacy and maximize cache hit coverage.

## Monitoring & Observability

### Logging
- Use consistent logger from `app.core.logging`
- Log at appropriate levels (info, warning, error)
- Include context (claim, source, score) in logs

### Metrics to Track
- Request latency by layer
- Evidence retrieval success rate
- Judge scoring distribution
- Cost per request (API calls)

### Debugging Helpers
- Log full pipeline path
- Track which retrievers were called
- Show evidence aggregation steps

## Future Enhancements

1. **More Retrieval Sources**
   - ArXiv for academic claims
   - Court records for legal facts
   - Company filings for financial data

2. **Fine-tuned Judge**
   - Train on labelled Q&A with hallucinations
   - Better accuracy than generic LLM

3. **Explainability**
   - Show which evidence supported which score
   - Highlight conflicting evidence
   - Confidence intervals, not just scores

4. **User Feedback Loop**
   - Users mark verdicts as correct/incorrect
   - Fine-tune judge based on feedback
   - Improve claim extraction

5. **Multilingual Support**
   - Extend to other languages
   - Handle translation of evidence

## References & Resources

- [Retrieval-Augmented Generation (RAG)](https://arxiv.org/abs/2005.11401)
- [Factuality in Language Models](https://arxiv.org/abs/2311.07700)
- [FastAPI Best Practices](https://fastapi.tiangolo.com/)
- [Pydantic Validation](https://docs.pydantic.dev/)
