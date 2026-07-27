# AI Hallucination Risk Assessment — Complete Backend System Summary

> **Status**: ✅ Backend Fully Implemented & Running  
> **Version**: 0.1.0  
> **Updated**: July 2026  
> **Stack**: Python · FastAPI · Pydantic v2 · Groq (llama-3.3-70b-versatile) · OpenAI / Anthropic · Wikipedia MediaWiki API · SerpAPI · Redis (Upstash) · MongoDB Atlas · motor · python-jose · slowapi · httpx (async)

---

## 1. What This System Does (The Big Picture)

AI language models are confident — sometimes too confident. They produce fluent, plausible text that can be factually wrong (a phenomenon called **hallucination**). This backend detects that risk by:

1. **Authenticating** the user via Google OAuth2 (handled in the Chrome Extension) and verifying a TruthLens-minted JWT on every API call.
2. **Receiving** a question and an AI-generated answer.
3. **Extracting** the key factual claims from the answer.
4. **Searching** trusted external sources (Wikipedia, Google via SerpAPI) for evidence.
5. **Grounding** an LLM judge in that evidence to score the answer.
6. **Returning** a structured hallucination-risk score + verdict + explanation to the caller.
7. **Persisting** a per-user audit log to MongoDB Atlas (via `BackgroundTasks`).

The frontend (a Chrome Extension — see `chrome-extension/`) calls this backend's REST API. The backend is the "brain" — the extension is the "face."

---

## 2. Architecture Philosophy

### Why Evidence-Grounded Judging?

A naive approach ("just ask GPT to judge the answer") fails because **the judge LLM can itself hallucinate**. The solution is **Retrieval-Augmented Judging (RAJ)**:

```
Question + Answer
      ↓
  Fetch real-world evidence from Wikipedia / Google
      ↓
  Feed (Question + Answer + Evidence) to LLM
      ↓
  LLM judges based ONLY on what the evidence says
```

This reduces false positives and makes the judge more reliable, because it is anchored to external ground truth.

### The 5-Layer Pipeline

The entire pipeline is implemented as a chain of discrete, independently testable layers:

```
Layer 1:  API Gateway         — HTTP entry point, JWT auth, rate limit, cache
Layer 2:  Query Preprocessor  — Claim extraction + query type classification
Layer 3:  Retrieval Engine    — Wikipedia + SerpAPI + routing + aggregation
Layer 4:  LLM Judge           — Evidence-grounded scoring via LLM
Layer 5:  Response Builder    — Maps score → user-friendly verdict
```

---

## 3. Project Structure (Fully Implemented)

```
AI-Hallucination-Risk-Assessment/
│
├── main.py                     # FastAPI app entrypoint, CORS, routing, lifespan
├── requirements.txt            # All Python dependencies
├── .env / .env.example         # Environment configuration
├── Dockerfile                  # Production container build
├── docker-compose.yml          # Local dev with Redis + MongoDB sidecar
│
├── app/
│   ├── api/
│   │   ├── dependencies.py         # get_current_user dependency (JWT → user dict)
│   │   └── routes/
│   │       ├── auth.py             # POST /api/auth/google-login (OAuth2 exchange)
│   │       ├── verify.py           # POST /api/verify, GET /api/health, GET /api/history
│   │       └── analytics.py        # GET /api/analytics (event tracking dashboard)
│   │
│   ├── core/
│   │   ├── auth.py                 # JWTVerifier singleton (HS256/RS256)
│   │   ├── cache.py                # Redis primary + TTLCache fallback
│   │   ├── config.py               # Pydantic Settings — all env var loading
│   │   ├── http_client.py          # Shared httpx.AsyncClient with connection pooling
│   │   ├── limiter.py              # SlowAPI user-scoped rate limiter (20 req/min)
│   │   └── logging.py              # Centralised logger factory
│   │
│   ├── db/
│   │   └── mongo.py                # Motor async client, UserHistoryRepository, indexes
│   │
│   ├── models/
│   │   ├── history.py              # UserHistoryRecord Pydantic model (MongoDB schema)
│   │   ├── request.py              # VerifyRequest model
│   │   └── response.py             # VerifyResponse + JudgeResponse + ClaimResult models
│   │
│   └── services/
│       ├── preprocessing/
│       │   └── query_preprocessor.py   # Layer 2
│       ├── retrieval/
│       │   ├── wikipedia_retriever.py  # Layer 3A
│       │   ├── serp_retriever.py       # Layer 3B
│       │   ├── source_router.py        # Layer 3C
│       │   └── evidence_aggregator.py  # Layer 3D
│       └── judge/
│           ├── llm_judge.py            # Layer 4 — multi-provider LLM judge
│           └── grok_mediator.py        # Grok (xAI) specialised mediator
│
├── chrome-extension/           # Browser extension frontend
│   ├── manifest.json           # Extension manifest (MV3), permissions, content scripts
│   ├── popup.html / popup.js   # Extension popup UI with Google Sign-In
│   ├── content.js              # Injected into web pages to capture AI responses
│   ├── ai-chat-injector.js     # Monitors ChatGPT/Claude/Gemini, intercepts Q&A pairs
│   └── background.js           # Service worker for message routing
│
├── dashboard/                  # Static HTML analytics dashboard (served at /dashboard)
├── analytics-dashboard/        # Static HTML event viewer (served at /analytics)
│
└── tests/                      # 144-test suite (pytest + pytest-asyncio)
```

---

## 4. Layer-by-Layer Implementation Details

### Layer 1 — API Gateway (`app/api/routes/verify.py`)

**Endpoints**: `POST /api/verify`, `GET /api/health`, `GET /api/history`

Every incoming request goes through this security lifecycle:

```
POST /api/verify
  → [1] JWT token verification via get_current_user dependency
  → [2] SlowAPI rate limiter (20 req/min per user_id)
  → [3] Global Redis cache lookup (key = SHA-256(question + answer))
      ├── CACHE HIT  → return immediately + spawn BackgroundTask (Mongo audit log)
      └── CACHE MISS → continue pipeline
  → [4] Layer 2: QueryPreprocessor.preprocess_async(question, answer)
  → [5] Layer 3: SourceRouter().retrieve_evidence(claims, query_type)
  → [6] Layer 3: EvidenceAggregator().aggregate(evidence_list)
  → [7] Layer 4: LLMJudge().judge(question, answer, aggregated_evidence)
  → [8] Layer 4b: LLMJudge().judge_per_claim(...)  ← Per-claim scoring
  → [9] Layer 5: VerifyResponse.from_judge_response(...)
  → [10] BackgroundTask: MongoDB audit log write
```

**Response example**:
```json
{
  "score": 85,
  "verdict": "accurate",
  "explanation": "Verified against Wikipedia. Paris is indeed the capital of France.",
  "flag": false,
  "sources_used": ["Wikipedia"],
  "request_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "processing_time_ms": 1250,
  "cache_hit": false,
  "provider": "groq",
  "model": "llama-3.3-70b-versatile",
  "claim_results": [
    {
      "claim_text": "Paris is the capital of France",
      "score": 95,
      "verdict": "accurate",
      "explanation": "Confirmed by Wikipedia."
    }
  ]
}
```

---

### Authentication — Google OAuth2 (`app/api/routes/auth.py`)

**Endpoint**: `POST /api/auth/google-login`

The Chrome Extension uses `chrome.identity.launchWebAuthFlow` (not `getAuthToken`) to allow full Google account selection/switching. The flow is:

1. Extension opens the Google OAuth2 consent screen via `launchWebAuthFlow`.
2. User selects their Google account and grants consent.
3. Extension receives a Google ID token and POSTs it to `POST /api/auth/google-login`.
4. Backend verifies the Google ID token against Google's public key endpoint.
5. Backend upserts the user in MongoDB (`users` collection).
6. Backend mints a TruthLens JWT (HS256, 1-hour expiry) and returns it.
7. Extension stores the JWT in `chrome.storage.local` and attaches it as `Authorization: Bearer <token>` on all subsequent API calls.

Expired tokens (401 response) are automatically detected in `content.js` and `ai-chat-injector.js`, which clear the stored token and prompt the user to re-sign in.

---

### Layer 2 — Query Preprocessor

Uses a **pure heuristic pipeline** (no LLM call, no external dependency):

1. **Split** the answer into sentences using regex (with abbreviation protection).
2. **Filter** for factual sentences (≥ 15 chars, not a question, not filler/opinion).
3. **Clean** each sentence (strip connectors, punctuation, collapse whitespace).
4. **Select** top `max_claims` (default: 3) by sentence length.

**Query type classification** (keyword/pattern matching, no LLM):

| Type | Detection | Routing Effect |
|---|---|---|
| `opinion_subjective` | `"should"`, `"recommend"` | Skip retrieval entirely |
| `numeric_statistical` | `"how many"`, `"how much"` | Wikipedia + SerpAPI |
| `recent_event` | `"today"`, `"latest"`, `"2024"`, `"2025"`, `"2026"` | SerpAPI first, Wikipedia fallback |
| `encyclopedic` | Default fallback | Wikipedia + SerpAPI |

---

### Layer 3A — Wikipedia Retriever

- Direct async `httpx.AsyncClient` HTTP calls to the MediaWiki API.
- Multi-term fallback search: extracts named entities first, falls back to the full query string.
- Results cached in-memory to avoid duplicate lookups within a request.

---

### Layer 3B — SerpAPI Retriever

- Uses `google-search-results` SDK.
- Skipped gracefully if `SERPAPI_KEY` is empty or placeholder.
- Extracts Answer Box + top 3 organic snippets.

---

### Layer 3C — Source Router

Routing rules (pure logic, no LLM):
```python
routing_rules = {
    "encyclopedic":        ["wikipedia", "serpapi"],
    "recent_event":        ["serpapi", "wikipedia"],
    "numeric_statistical": ["wikipedia", "serpapi"],
    "opinion_subjective":  [],
}
```
Uses `asyncio.gather(return_exceptions=True)` — individual retriever failures never break the pipeline.

---

### Layer 3D — Evidence Aggregator

4-step pipeline:
1. **Flatten** combined per-source strings into individual paragraphs.
2. **Deduplicate** (exact + substring containment removal).
3. **Rank** by quality score (length, numerical content, boilerplate penalty).
4. **Trim** to token budget (default: 2000 tokens ≈ 8,000 chars), cutting at sentence boundaries.

---

### Layer 4 — LLM Judge (`app/services/judge/llm_judge.py`)

**Active provider**: `groq` with `llama-3.3-70b-versatile` (fast, free, recommended).

| `LLM_PROVIDER` | SDK | Status |
|---|---|---|
| `groq` | `openai` (compat endpoint) | ✅ **Active** — Free, ~3s response |
| `gemini` | `openai` (compat endpoint) | ⚠️ Free tier quota exhausts quickly |
| `openai` | `openai` | ⚠️ Requires paid billing |
| `grok` | `openai` (custom base URL) | ✅ Supported |
| `anthropic` | `anthropic` (native SDK) | ✅ Supported |
| `groq` + `llama3-70b-8192` | — | ❌ Decommissioned — use `llama-3.3-70b-versatile` |

**Heuristic fallback judge**: When LLM API is unavailable, falls back to keyword-overlap scoring so a response is always returned.

---

### Layer 5 — Response Builder (`app/models/response.py`)

| Judge Score | Internal Verdict | User-Facing Verdict |
|---|---|---|
| 75 – 100 | `verified` | `accurate` ✅ |
| 40 – 74 | `unverifiable` | `uncertain` ⚠️ |
| 0 – 39 | `likely_hallucination` | `hallucination` 🚩 |

---

## 5. Data Models

### Input (`VerifyRequest`)
```python
class VerifyRequest(BaseModel):
    question: str  # 5–2000 characters, whitespace-stripped
    answer: str    # 5–5000 characters, whitespace-stripped
```

### Output (`VerifyResponse`)
```python
class VerifyResponse(BaseModel):
    score: int
    verdict: Literal["accurate", "uncertain", "hallucination"]
    explanation: str
    flag: bool
    sources_used: Optional[list[str]]
    request_id: Optional[str]
    processing_time_ms: Optional[int]
    cache_hit: bool
    provider: Optional[str]
    model: Optional[str]
    claim_results: Optional[list[ClaimResult]]
```

---

## 6. Configuration (`.env`)

| Variable | Current Value / Default | Description |
|---|---|---|
| `APP_DEBUG` | `false` | Debug mode |
| `HOST` | `0.0.0.0` | Server bind host |
| `PORT` | `8000` | Server bind port |
| `LLM_PROVIDER` | `groq` | Active LLM provider |
| `LLM_API_KEY` | *(your Groq key)* | API key |
| `LLM_MODEL` | `llama-3.3-70b-versatile` | Active model |
| `SERPAPI_KEY` | *(your SerpAPI key)* | Optional web search |
| `REDIS_URL` | `rediss://...upstash.io:6379` | Upstash Redis (cloud) |
| `REDIS_ENABLED` | `true` | Toggle Redis |
| `CACHE_ENABLED` | `true` | Toggle caching |
| `CACHE_TTL_SECONDS` | `3600` | Default TTL |
| `ALLOWED_ORIGINS` | `["chrome-extension://iffeaoceohaoncddifljbjjkgakpgmie"]` | CORS lockdown |
| `JWT_SECRET` | *(your secret)* | HS256 signing secret |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_EXPIRY_SECONDS` | `3600` | Token lifetime (1 hr) |
| `MONGODB_URL` | `mongodb+srv://...atlas.mongodb.net` | MongoDB Atlas (cloud) |
| `DATABASE_NAME` | `aimatrix_db` | MongoDB database name |
| `MAX_EVIDENCE_TOKENS` | `800` | Evidence budget per claim |
| `MAX_CLAIMS_PER_REQUEST` | `3` | Max claims extracted |

---

## 7. Application Entry Point (`main.py`)

**Routers registered**:
- `auth_router` → `/api/auth/google-login`
- `verify_router` → `/api/verify`, `/api/health`, `/api/history`
- `analytics_router` → `/api/analytics`

**Static mounts**:
- `/dashboard` → `dashboard/` directory
- `/analytics` → `analytics-dashboard/` directory

**CORS**: Locked down to `ALLOWED_ORIGINS` from `.env`. Currently set to the production Chrome Extension ID.

**Startup sequence** (via `asynccontextmanager lifespan`):
1. Init Redis cache (Upstash)
2. Create shared `httpx.AsyncClient`
3. Init `SourceRouter`, `LLMJudge`, `EvidenceAggregator`, `GrokMediator` singletons
4. Init `JWTVerifier` singleton
5. Init MongoDB Atlas connection

---

## 8. Dependencies (`requirements.txt`)

```
fastapi==0.104.1
uvicorn[standard]==0.24.0
pydantic>=2.10.0
pydantic-settings>=2.1.0
python-dotenv>=1.0.0

# Caching
cachetools>=5.3.0
redis[asyncio]>=5.0.0        # Upstash Redis (cloud)

# External APIs
wikipedia-api>=0.12.0
google-search-results>=2.4.0

# LLM Clients
openai>=1.3.0               # Groq / Gemini / Grok via compat endpoint
anthropic>=0.39.0           # Native Claude support

# Authentication
python-jose[cryptography]>=3.3.0   # JWT verification (HS256/RS256)

# Rate Limiting
slowapi>=0.1.9

# Database
motor>=3.3.0                # Async MongoDB Atlas driver
pymongo>=4.6.0              # Required by motor

# Testing
pytest>=7.4.3
pytest-asyncio>=0.21.1
httpx>=0.25.2
```

---

## 9. API Endpoints Reference

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/auth/google-login` | None | Exchange Google ID token for TruthLens JWT |
| `POST` | `/api/verify` | ✅ JWT | Verify AI answer for hallucination risk |
| `GET` | `/api/history` | ✅ JWT | Paginated per-user verification history |
| `GET` | `/api/health` | None | Health check |
| `GET` | `/api/analytics` | None | Event analytics dashboard |
| `GET` | `/dashboard` | None | Static analytics dashboard UI |
| `GET` | `/` | None | Server info |

---

## 10. Cloud Infrastructure (Current State)

| Service | Provider | URL |
|---|---|---|
| **Database** | MongoDB Atlas (M0 Free) | `cluster0.urjkyki.mongodb.net` |
| **Cache** | Upstash Redis (Free) | `tender-bat-147716.upstash.io:6379` |
| **Backend** | `localhost:8000` (local) | *Pending: Render/Cloud Run deployment* |
| **Extension** | Chrome Web Store (unpacked) | ID: `iffeaoceohaoncddifljbjjkgakpgmie` |

---

## 11. Error Handling & Graceful Degradation

| Failure Point | Behaviour |
|---|---|
| Missing/invalid JWT | HTTP 401 Unauthorized |
| Expired JWT | HTTP 401 (detected by Extension → re-prompt sign-in) |
| Rate limit exceeded | HTTP 429 Too Many Requests |
| Input too short/long | HTTP 422 Unprocessable Entity |
| Wikipedia timeout | Continue with empty evidence, log warning |
| SerpAPI missing key | Skip silently, log warning |
| LLM API unavailable | Fall back to keyword-overlap heuristic judge |
| LLM returns invalid JSON | Fall back to heuristic judge |
| MongoDB unavailable | `app.state.db = None` — history persistence disabled, API still works |
| Redis unavailable | Fall back to in-memory TTLCache — cache doesn't persist across restarts |

---

## 12. Caching Architecture (`app/core/cache.py`)

- **Primary**: Upstash Redis (cloud, persistent, TTL-evicted server-side).
- **Fallback**: Thread-safe in-memory `cachetools.TTLCache` (max 1000 items, 1-hour TTL, protected by `asyncio.Lock`).
- **Cache Key**: `verify_{SHA-256(question + answer)}` — global across all users.
- **TTL Policies**:
  - `encyclopedic`: 7 days
  - `numeric_statistical`: 24 hours
  - `recent_event`: 1 hour
  - `opinion_subjective`: 30 minutes

---

## 13. Chrome Extension Frontend

| File | Role |
|---|---|
| `manifest.json` | MV3 manifest, permissions (`storage`, `identity`), content scripts |
| `popup.html/js` | Extension popup UI with Google Sign-In button |
| `content.js` | Injected into web pages; captures AI responses; handles 401 token expiry |
| `ai-chat-injector.js` | Monitors ChatGPT/Claude/Gemini chat interfaces; intercepts Q&A pairs; handles 401 expiry |
| `background.js` | Service worker for cross-tab message routing |

The extension uses `chrome.identity.launchWebAuthFlow` (not the legacy `getAuthToken`) to support full Google account switching.

---

## 14. Security Summary

1. **CORS Lockdown**: `ALLOWED_ORIGINS` is set to `["chrome-extension://iffeaoceohaoncddifljbjjkgakpgmie"]` — rejects all other origins.
2. **JWT Authentication**: Every protected endpoint requires `Authorization: Bearer <token>`. Tokens are verified via `JWTVerifier` (HS256).
3. **User-Scoped Rate Limiting**: 20 requests/min keyed to `user_id` from the JWT `sub` claim (not client IP).
4. **Database Isolation**: History records are written per `user_id`. Redis cache is global/anonymous.
5. **Token Expiry**: 1-hour JWT expiry. Extension auto-detects 401 and prompts re-authentication.
