# Verification Guide

## Prerequisites

```bash
# Windows (PowerShell)
.\venv\Scripts\activate

# Mac/Linux
# source venv/bin/activate
```

---

## Layer 1: API Gateway

### Automated Tests

```bash
python -m pytest tests/test_models.py tests/test_verify.py -v
```

**Expected**: 31 tests pass (21 model + 10 endpoint)

### Manual Testing

Start the server:
```bash
python main.py
```

In another terminal (ensure you have a valid JWT token matching the configured `JWT_SECRET` on the backend):

```bash
# ✅ Valid request → 200 with score, verdict, request_id, processing_time_ms
curl -s -X POST http://localhost:8000/api/verify \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <jwt-token>' \
  -d '{"question": "What is the capital of France?", "answer": "Paris is the capital of France."}' | python3 -m json.tool

# ❌ Question too short → 422
curl -s -X POST http://localhost:8000/api/verify \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <jwt-token>' \
  -d '{"question": "Hi", "answer": "Paris is the capital of France."}' | python3 -m json.tool

# ❌ Missing field → 422
curl -s -X POST http://localhost:8000/api/verify \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <jwt-token>' \
  -d '{"question": "What is the capital of France?"}' | python3 -m json.tool

# 💚 Health check (no auth required) → {"status": "ok"}
curl -s http://localhost:8000/api/health | python3 -m json.tool
```

### Interactive Docs

Visit **http://localhost:8000/docs** for Swagger UI.

### Expected Output (Production Mode)

Since all layers are fully implemented, valid requests return:
- Fact-grounded `score`, `verdict`, and `explanation` from the LLM judge.
- `request_id` (UUID) and `processing_time_ms`.
- Subsequent identical requests return in `<5ms` due to global Redis caching.
- Server logs show the request_id tracing across all 5 layers of the pipeline.

---

## Layer 2: Query Preprocessor

### Automated Tests

```bash
python -m pytest tests/test_preprocessor.py -v
```

**Expected**: 24 tests pass (9 extraction + 12 query type + 3 pipeline)

### Quick Manual Test

```bash
python -c "
from app.services.preprocessing.query_preprocessor import QueryPreprocessor

# Test claim extraction
claims = QueryPreprocessor.extract_claims(
    'Paris is the capital of France. It is located along the Seine River. The city has over 2 million residents.'
)
print('Claims:', claims)

# Test query type detection
print('Type:', QueryPreprocessor.determine_query_type('What is the capital of France?'))
print('Type:', QueryPreprocessor.determine_query_type('What happened today in politics?'))
print('Type:', QueryPreprocessor.determine_query_type('How many countries are in the EU?'))
print('Type:', QueryPreprocessor.determine_query_type('Should I learn Python or JavaScript?'))
"
```

---

## Layer 3: Retrieval Engine

### Automated Tests

```bash
python -m pytest tests/test_retrievers.py -v
```

**Expected**: 25 tests pass (5 Wikipedia + 3 SerpAPI + 8 router + 9 aggregator)

### Quick Manual Test

```bash
python -c "
from app.services.retrieval.wikipedia_retriever import WikipediaRetriever

retriever = WikipediaRetriever()
result = retriever.search('Paris')
print('Found:', result['found'])
print('Title:', result['title'])
print('Content:', result['content'][:200] if result['content'] else 'None')
"
```

---

## Layer 4: LLM Judge

### Automated Tests

```bash
python -m pytest tests/test_judge.py -v
```

**Expected**: 14 tests pass (3 prompt + 7 parsing + 4 judge)

### Setup

Ensure your `.env` is configured with the active provider:
```bash
LLM_PROVIDER=groq
LLM_API_KEY=your_groq_api_key
LLM_MODEL=llama-3.3-70b-versatile
```

> ⚠️ Do NOT use `LLM_PROVIDER=gemini` unless you have a working API key with sufficient quota. The default active provider is **Groq** (free, fast, recommended).

### Full Pipeline Test

With a valid `.env` and database setup, restart the server and test end-to-end:

```bash
python main.py
```

```bash
# Verify claims (requires a valid JWT token)
curl -s -X POST http://localhost:8000/api/verify \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <jwt-token>' \
  -d '{"question": "What is the capital of France?", "answer": "Paris is the capital of France."}' | python3 -m json.tool
```

**Expected**: Real score, verdict, explanation from LLM judge.

---

## Security & History Audit Logs

### Automated Tests
```bash
python -m pytest tests/test_security.py tests/test_auth_history.py -v
```
**Expected**: 50 tests pass (21 security + 29 history validation)

### Manual Testing

Ensure your MongoDB instance is running (or configured in `.env`). Perform a few verification requests first to populate the history.

```bash
# 1. Retrieve history (authenticated) → returns list of user history records
curl -s -X GET "http://localhost:8000/api/history?skip=0&limit=5" \
  -H 'Authorization: Bearer <jwt-token>' | python3 -m json.tool

# 2. Retrieve history (unauthenticated) → returns 403 Forbidden
curl -s -X GET "http://localhost:8000/api/history" | python3 -m json.tool
```

---

## Run All Tests

```bash
python -m pytest tests/ -v
```

**Expected**: 144 tests pass
