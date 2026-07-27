# Quick Start Guide

## 60-Second Setup

### 1. Clone & Install
```bash
git clone <repo-url>
cd AI-Hallucination-Risk-Assessment
python -m venv venv
.\venv\Scripts\activate        # Windows
# source venv/bin/activate     # Mac/Linux
pip install -r requirements.txt
```

### 2. Configure
```bash
cp .env.example .env
# Edit .env — fill in the following required values:
# LLM_PROVIDER=groq
# LLM_API_KEY=your_groq_key_here        (get free at console.groq.com)
# LLM_MODEL=llama-3.3-70b-versatile
# SERPAPI_KEY=your_serpapi_key_here      (optional — 100 free/month at serpapi.com)
# JWT_SECRET=your_random_secret_string
# MONGODB_URL=mongodb+srv://...          (MongoDB Atlas connection string)
# REDIS_URL=rediss://...                 (Upstash Redis connection string)
# ALLOWED_ORIGINS=["chrome-extension://YOUR_EXTENSION_ID"]
```

### 3. Run Server
```bash
python main.py
```

Server starts at `http://localhost:8000`. Successful startup shows:
```
INFO - Redis cache connected: rediss://...upstash.io
INFO - MongoDB singleton initialised — db='aimatrix_db'
INFO - Application startup complete.
INFO - Uvicorn running on http://0.0.0.0:8000
```

### 4. Test Endpoint

First generate a test JWT token:
```bash
python generate_test_token.py
```

Then verify a claim:
```bash
curl -X POST "http://localhost:8000/api/verify" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{"question": "What is the capital of France?", "answer": "Paris is the capital of France."}'
```

---

## Project Structure at a Glance

```
app/
├── api/
│   ├── dependencies.py          ← JWT → user extraction (get_current_user)
│   └── routes/
│       ├── auth.py              ← POST /api/auth/google-login (OAuth2)
│       ├── verify.py            ← POST /api/verify, GET /api/history, GET /api/health
│       └── analytics.py         ← GET /api/analytics
├── core/
│   ├── auth.py                  ← JWTVerifier singleton
│   ├── cache.py                 ← Redis + TTLCache fallback
│   ├── config.py                ← All settings loaded from .env
│   ├── limiter.py               ← SlowAPI rate limiter (20/min per user)
│   └── http_client.py           ← Shared httpx.AsyncClient
├── db/
│   └── mongo.py                 ← MongoDB Atlas connection + UserHistoryRepository
├── models/
│   ├── request.py               ← VerifyRequest (Pydantic v2)
│   ├── response.py              ← VerifyResponse + ClaimResult + JudgeResponse
│   └── history.py               ← UserHistoryRecord (MongoDB schema)
└── services/
    ├── preprocessing/            ← Layer 2 (claim extraction)
    ├── retrieval/                ← Layer 3 (Wikipedia, SerpAPI, etc.)
    └── judge/                    ← Layer 4 (LLM verification)
```

---

## Implementation Status

- ✅ **Done**: 5-Layer pipeline (API Gateway → Preprocessor → Retrieval → LLM Judge → Response)
- ✅ **Done**: Multi-provider LLM support (Groq active, OpenAI/Gemini/Anthropic/Grok supported)
- ✅ **Done**: Global Redis caching (Upstash cloud) with in-memory TTLCache fallback
- ✅ **Done**: Async MongoDB per-user history tracking (MongoDB Atlas cloud)
- ✅ **Done**: Google OAuth2 via `chrome.identity.launchWebAuthFlow` + TruthLens JWT minting
- ✅ **Done**: JWT bearer token authorization (`python-jose`, HS256)
- ✅ **Done**: User-scoped rate limiting (SlowAPI, 20 req/min)
- ✅ **Done**: Per-claim scoring with `ClaimResult` model
- ✅ **Done**: CORS lockdown to production Chrome Extension ID
- ✅ **Done**: 401 token-expiry auto-handling in extension (content.js + ai-chat-injector.js)
- ✅ **Done**: Analytics dashboard (served at `/analytics`)
- 🔲 **Pending**: Cloud backend deployment (Render / Google Cloud Run)

---

## API Reference

### POST /api/auth/google-login
Exchange a Google ID token for a TruthLens JWT.

**Headers**: `Content-Type: application/json`

**Request Body**:
```json
{
  "id_token": "<Google ID token from OAuth2 flow>"
}
```

**Response (200 OK)**:
```json
{
  "access_token": "<TruthLens JWT>",
  "token_type": "bearer",
  "user": { "email": "...", "name": "...", "picture": "..." }
}
```

---

### POST /api/verify
Verify if an AI answer contains hallucinations.

**Headers**:
- `Authorization: Bearer <jwt-token>` (Required)
- `Content-Type: application/json`

**Request Body**:
```json
{
  "question": "string (5-2000 chars)",
  "answer": "string (5-5000 chars)"
}
```

**Response (200 OK)**:
```json
{
  "score": 0-100,
  "verdict": "accurate" | "uncertain" | "hallucination",
  "explanation": "string",
  "flag": true | false,
  "sources_used": ["Wikipedia", "SerpAPI"] | null,
  "request_id": "string (UUID)",
  "processing_time_ms": 1250,
  "cache_hit": false,
  "provider": "groq",
  "model": "llama-3.3-70b-versatile",
  "claim_results": [...]
}
```

**Error Responses**:
- `401`: Authentication failed (invalid/expired JWT) → Extension clears token and prompts re-sign-in
- `429`: Too Many Requests (20 req/min limit exceeded)
- `422`: Invalid input (missing fields, too short/long)
- `500`: Preprocessing pipeline failure

---

### GET /api/history
Retrieve paginated audit history for the authenticated user.

**Headers**: `Authorization: Bearer <jwt-token>` (Required)

**Query Parameters**:
- `skip` (int, default `0`): Number of records to skip
- `limit` (int, default `10`): Max records to return

**Response (200 OK)**:
```json
[
  {
    "user_id": "string",
    "request_id": "string (UUID)",
    "question": "string",
    "score": 85,
    "verdict": "accurate",
    "cache_hit": false,
    "timestamp": "2026-07-27T12:44:12Z"
  }
]
```

---

### GET /api/health
Health check (no auth required).

**Response**:
```json
{ "status": "ok", "service": "hallucination-detection" }
```

---

## Example Requests

### Simple Fact Check
```bash
curl -X POST "http://localhost:8000/api/verify" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "question": "What is the capital of France?",
    "answer": "The capital of France is Paris, located on the Seine River."
  }'
```
Expected: Score 80+, `"accurate"`

### Hallucination Example
```bash
curl -X POST "http://localhost:8000/api/verify" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "question": "Who invented the telephone?",
    "answer": "The telephone was invented by Elon Musk in 1997."
  }'
```
Expected: Score < 40, `"hallucination"`

### View Your History
```bash
curl -X GET "http://localhost:8000/api/history?skip=0&limit=10" \
  -H "Authorization: Bearer <jwt-token>"
```

---

## Score Ranges

| Score | Verdict | Badge | Warning |
|-------|---------|-------|---------|
| 75-100 | accurate | ✅ Green | None |
| 40-74 | uncertain | ⚠️ Yellow | "Verify this information" |
| 0-39 | hallucination | 🚩 Red | "High hallucination risk" |

---

## Common Issues

### MongoDB or Redis Not Connecting
Check your `.env` file — make sure the values don't have duplicate variable names:
```env
# ✅ Correct
MONGODB_URL=mongodb+srv://user:pass@cluster0.xyz.mongodb.net/...
REDIS_URL=rediss://default:password@endpoint.upstash.io:6379

# ❌ Wrong (causes "Invalid URI scheme" error)
MONGODB_URL=MONGODB_URL=mongodb+srv://...
REDIS_URL=REDIS_URL="rediss://..."
```

### Module Import Errors
```bash
# Make sure venv is activated first!
.\venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### JWT Authentication Errors
Use `generate_test_token.py` to generate a valid test token using the same `JWT_SECRET` as your `.env`:
```bash
python generate_test_token.py
```

### Port Already in Use
```bash
# Windows: find and kill process on port 8000
netstat -ano | findstr :8000
taskkill /PID <pid> /F
```

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_PROVIDER` | Yes | `groq` | `groq`, `gemini`, `openai`, `anthropic`, `grok` |
| `LLM_API_KEY` | Yes | — | API key for chosen provider |
| `LLM_MODEL` | No | `llama-3.3-70b-versatile` | Model name |
| `SERPAPI_KEY` | No | — | SerpAPI key (optional, graceful skip) |
| `JWT_SECRET` | Yes | — | Random secret string for HS256 signing |
| `MONGODB_URL` | Yes | — | MongoDB Atlas `mongodb+srv://` string |
| `REDIS_URL` | Yes | — | Upstash `rediss://` connection string |
| `ALLOWED_ORIGINS` | Yes | — | Chrome Extension origin ID |

---

## Run Tests
```bash
# Run full test suite (144 tests)
python -m pytest tests/ -v

# Run specific test files
python -m pytest tests/test_security.py -v    # 21 security tests
python -m pytest tests/test_verify.py -v     # 10 integration tests
python -m pytest tests/test_judge.py -v      # 14 judge tests
```

---

## Interactive API Docs
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Analytics Dashboard**: http://localhost:8000/analytics
