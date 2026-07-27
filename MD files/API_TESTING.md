# API Testing - Postman Collection

This file documents API endpoints for testing with Postman or curl.

## Collection Variables

```json
{
  "base_url": "http://localhost:8000",
  "api_base": "http://localhost:8000/api"
}
```

> **Note**: The active LLM provider is **Groq** (`llama-3.3-70b-versatile`). Response `provider` and `model` fields will reflect this.
> A valid JWT token is required for all endpoints except `/api/health` and `/api/auth/google-login`.
> Generate a test token with: `python generate_test_token.py`

---

## Endpoint 0: Google OAuth2 Login

**Name**: Google Login  
**Method**: POST  
**URL**: `{{api_base}}/auth/google-login`  

### Request Body
```json
{
  "id_token": "<Google ID token from chrome.identity.launchWebAuthFlow>"
}
```

### Response
```json
{
  "access_token": "<TruthLens JWT>",
  "token_type": "bearer",
  "user": { "email": "user@gmail.com", "name": "User Name", "picture": "https://..." }
}
```

---

## Endpoint 1: Health Check

**Name**: Health Check  
**Method**: GET  
**URL**: `{{api_base}}/health`  

### Response
```json
{
  "status": "ok",
  "service": "hallucination-detection"
}
```

---

## Endpoint 2: Server Info

**Name**: Server Info  
**Method**: GET  
**URL**: `{{base_url}}/`  

### Response
```json
{
  "name": "AI Hallucination Detection Backend",
  "version": "0.1.0",
  "status": "running"
}
```

---

## Endpoint 3: Verify Answer

**Name**: Verify Hallucination  
**Method**: POST  
**URL**: `{{api_base}}/verify`  

### Headers
```
Content-Type: application/json
Authorization: Bearer <jwt-token>
```

### Request Body

#### Test Case 1: Accurate Answer
```json
{
  "question": "What is the capital of France?",
  "answer": "The capital of France is Paris, located along the Seine River in northern France."
}
```

**Expected Response** (Score: 75-100):
```json
{
  "score": 85,
  "verdict": "accurate",
  "explanation": "Verified against Wikipedia. Paris is indeed the capital of France.",
  "flag": false,
  "sources_used": ["Wikipedia"],
  "cache_hit": false,
  "provider": "groq",
  "model": "llama-3.3-70b-versatile"
}
```

---

#### Test Case 2: Hallucination
```json
{
  "question": "Who is the current president of France?",
  "answer": "Vincent Van Gogh is the current president of France (as of 2024)."
}
```

**Expected Response** (Score: 0-39):
```json
{
  "score": 5,
  "verdict": "hallucination",
  "explanation": "Vincent Van Gogh was a 19th-century artist who died in 1890. This is factually incorrect.",
  "flag": true,
  "sources_used": ["Wikipedia"],
  "cache_hit": false,
  "provider": "groq",
  "model": "llama-3.3-70b-versatile"
}
```

---

#### Test Case 3: Uncertain/Unverifiable
```json
{
  "question": "What will the weather be tomorrow?",
  "answer": "Tomorrow will be sunny with 72°F temperature."
}
```

**Expected Response** (Score: 40-74):
```json
{
  "score": 50,
  "verdict": "uncertain",
  "explanation": "Future weather predictions cannot be verified against current sources.",
  "flag": false,
  "sources_used": null
}
```

---

#### Test Case 4: Complex Multi-Claim Answer
```json
{
  "question": "Tell me about the Moon",
  "answer": "The Moon is Earth's natural satellite. It orbits Earth every 27.3 days and has a diameter of about 3,474 km. The Moon was formed about 4.5 billion years ago from a giant impact theory hypothesis."
}
```

**Expected Response**:
```json
{
  "score": 78,
  "verdict": "accurate",
  "explanation": "Key facts verified: Moon is Earth's satellite, orbital period ~27 days, diameter ~3,474 km, formation ~4.5B years ago.",
  "flag": false,
  "sources_used": ["Wikipedia"]
}
```

---

#### Test Case 5: Recent Event (Requires SerpAPI)
```json
{
  "question": "What happened in recent tech news?",
  "answer": "A new AI model breakthrough was announced in January 2024 demonstrating improved reasoning capabilities."
}
```

**Expected Response**:
```json
{
  "score": 65,
  "verdict": "uncertain",
  "explanation": "Multiple AI breakthroughs claimed in early 2024. Need more specific details to verify exact claim.",
  "flag": false,
  "sources_used": ["SerpAPI"]
}
```

---

#### Test Case 6: Invalid Input - Missing Field
```json
{
  "question": "What is 2+2?"
}
```

**Expected Response** (422):
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "answer"],
      "msg": "Field required"
    }
  ]
}
```

---

#### Test Case 7: Invalid Input - Too Short
```json
{
  "question": "Hi?",
  "answer": "42"
}
```

**Expected Response** (422):
```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "question"],
      "msg": "String should have at least 5 characters"
    }
  ]
}
```

---

## Endpoint 4: Get History

**Name**: Get History  
**Method**: GET  
**URL**: `{{api_base}}/history`  

### Headers
```
Authorization: Bearer <jwt-token>
```

### Query Parameters
- `skip` (optional, integer): Number of records to skip (default: 0)
- `limit` (optional, integer): Max number of records to return (default: 10)

### Response
```json
[
  {
    "user_id": "test-user-123",
    "request_id": "d3b07384-d113-4ec4-a55e-1ec862d8b4d8",
    "question": "What is the capital of France?",
    "score": 85,
    "verdict": "accurate",
    "cache_hit": false,
    "timestamp": "2026-05-22T00:00:00Z"
  }
]
```

---

## curl Commands for Quick Testing

### Test 1: Verify with curl
```bash
curl -X POST "http://localhost:8000/api/verify" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "question": "What is the capital of France?",
    "answer": "Paris is the capital of France."
  }'
```

### Test 2: Hallucination Detection
```bash
curl -X POST "http://localhost:8000/api/verify" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "question": "Who discovered America?",
    "answer": "The Earth is located in the Andromeda Galaxy."
  }'
```

### Test 3: Health Check
```bash
curl http://localhost:8000/api/health
```

### Test 4: Pretty Print Response
```bash
curl -X POST "http://localhost:8000/api/verify" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "question": "What is Python?",
    "answer": "Python is a programming language."
  }' | python -m json.tool
```

### Test 5: Get History with curl
```bash
curl -X GET "http://localhost:8000/api/history?skip=0&limit=10" \
  -H "Authorization: Bearer <jwt-token>"
```

---

## Building Custom Postman Collection

1. **Import into Postman**:
   - Click "Import"
   - Paste this file or import from URL
   - Set `{{base_url}}` variable to `http://localhost:8000`

2. **Create Variables**:
   - Environment name: "Local"
   - Variables:
     - `base_url`: `http://localhost:8000`
     - `api_base`: `http://localhost:8000/api`

3. **Run Tests**:
   - Select a request
   - Click "Send"
   - View response in "Body" tab

4. **Automate**:
   - Click "Runner"
   - Select collection
   - Select environment "Local"
   - Click "Start Test Run"

---

## Expected Score Ranges

| Score | Verdict | UI Badge | Warning |
|-------|---------|----------|---------|
| 75-100 | accurate | ✅ Green | None |
| 40-74 | uncertain | ⚠️ Yellow | "Verify this information" |
| 0-39 | hallucination | 🚩 Red | "High hallucination risk" |

---

## Response Time Targets

- **Health Check**: <10ms
- **Simple Verify**: 2-8 seconds (typical)
  - 1ms: Preprocessing (claim extraction)
  - 1-3s: Wikipedia/SerpAPI retrieval
  - 1-5s: LLM judge call
  - Per-layer timing is included in `debug.timing` in the response

---

## Debugging Tips

### View Full Response Headers
```bash
curl -X POST "http://localhost:8000/api/verify" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{"question": "Test?", "answer": "Test answer"}' \
  -i
```

### View Request/Response with Details
```bash
curl -X POST "http://localhost:8000/api/verify" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{"question": "Test?", "answer": "Test answer"}' \
  -v
```

### Test with Python
```python
import requests
import json

response = requests.post(
    "http://localhost:8000/api/verify",
    json={"question": "Test?", "answer": "Test answer"},
    headers={"Authorization": "Bearer <jwt-token>"},
    timeout=30
)

print(f"Status: {response.status_code}")
print(f"Response: {json.dumps(response.json(), indent=2)}")
```

---

## Success Criteria

- ✅ All requests return proper HTTP status codes
- ✅ Responses match expected JSON schema
- ✅ Scores are between 0-100
- ✅ Verdicts are one of: "accurate", "uncertain", "hallucination"
- ✅ Response times are reasonable (<15 seconds)

---

**Note**: As backend develops, add actual responses here to track progress!
