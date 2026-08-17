# TruthLens

TruthLens is an AI-answer verification system that checks factual claims in generated text against retrieved evidence and returns an evidence-grounded score, verdict, explanation, and per-claim breakdown.

The repository contains:

- An asynchronous FastAPI backend.
- A Manifest V3 Chrome extension for verifying text on web pages and supported AI chat sites.
- A basic dashboard at `/dashboard` and a deeper pipeline analytics dashboard at `/analytics`.

## Why use TruthLens?

- **Claim-level verification:** Extracts factual claims from an answer and can score individual claims.
- **Evidence retrieval:** Routes queries to sources such as Wikipedia, SerpAPI, Google Scholar, government sites, news, medical sources, and finance sources.
- **Multiple LLM providers:** Supports Groq, Gemini, OpenAI-compatible providers, xAI Grok, and Anthropic through configuration.
- **Resilient operation:** Retrieval failures, unavailable LLMs, MongoDB outages, and Redis outages degrade gracefully where possible.
- **Authenticated history:** JWT-protected verification and per-user history storage in MongoDB.
- **Caching and rate limiting:** Redis caching with an in-memory fallback, plus a user-scoped limit of 20 verification requests per minute.
- **Browser workflow:** Adds verification controls to ordinary web pages and ChatGPT, Claude, Gemini, and Perplexity conversations.

TruthLens is an assistive verification tool. A high score indicates that the available evidence supports the answer; it is not a substitute for expert review or primary-source checking.

## How it works

```text
Request
  -> JWT authentication and rate limiting
  -> Claim extraction and query classification
  -> Parallel evidence retrieval
  -> Evidence aggregation and source-consensus check
  -> LLM judge with heuristic fallback
  -> Overall and per-claim response
  -> Cached result and asynchronous history record
```

The response score is on a 0–100 scale:

| Score | Verdict |
| ---: | --- |
| 70–100 | `accurate` |
| 40–69 | `uncertain` |
| 0–39 | `hallucination` |

## Getting started

### Prerequisites

- Python 3.10 or newer.
- A supported LLM API key for best results. Groq is the configured default.
- Optional: a SerpAPI key for web, news, academic, government, medical, and finance retrieval.
- Optional: Redis for persistent/shared caching.
- Optional: MongoDB for Google-login user records and per-user history.
- Optional: Google Chrome for the extension.

### Local backend setup

From this directory:

```bash
python -m venv venv

# Windows PowerShell
.\venv\Scripts\Activate.ps1

# macOS/Linux
# source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env  # PowerShell: Copy-Item .env.example .env
```

Edit `.env` and set at least a signing secret. For LLM-backed judgments, also set `LLM_API_KEY`:

```dotenv
LLM_PROVIDER=groq
LLM_API_KEY=your_groq_api_key
LLM_MODEL=llama-3.3-70b-versatile
JWT_SECRET=replace_with_a_long_random_secret

# Optional for a dependency-light local run
REDIS_ENABLED=false
MONGODB_URL=mongodb://localhost:27017

# Optional: enables SerpAPI-backed retrieval
SERPAPI_KEY=your_serpapi_key
```

The application will use an in-memory cache when Redis is disabled or unreachable. If MongoDB is unavailable, verification still runs but user history and user upserts are disabled.

Start the API:

```bash
python main.py
```

The server listens on [http://localhost:8000](http://localhost:8000). Interactive API documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs), with ReDoc at [http://localhost:8000/redoc](http://localhost:8000/redoc).

### Verify an answer through the API

`POST /api/verify` requires a TruthLens JWT. For local testing, generate one using the same `JWT_SECRET` configured in `.env`:

```bash
python generate_test_token.py
```

Then send a request with the printed token:

```bash
curl -X POST http://localhost:8000/api/verify \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <jwt-token>" \
  -d '{
    "question": "What is the capital of France?",
    "answer": "Paris is the capital of France."
  }'
```

The response includes `score`, `verdict`, `explanation`, `sources_used`, `processing_time_ms`, `cache_hit`, and, when available, `claim_results`.

### Run with Docker Compose

Docker Compose starts the FastAPI backend and a Redis 7 cache:

```bash
Copy-Item .env.example .env  # PowerShell
docker compose up --build
```

The Compose file does not start MongoDB. Set `MONGODB_URL` to a MongoDB instance reachable from the backend container if history and Google login are required. The backend remains usable without MongoDB, with history persistence disabled.

### Load the Chrome extension locally

1. Open `chrome://extensions` in Chrome.
2. Enable **Developer mode**.
3. Select **Load unpacked** and choose the `chrome-extension` directory.
4. Open the TruthLens extension popup and sign in with Google.

The checked-in extension currently targets the deployed backend URL in `chrome-extension/popup.js`, `chrome-extension/content.js`, and `chrome-extension/ai-chat-injector.js`. To use a local backend, change those API base URLs to `http://localhost:8000` and ensure `ALLOWED_ORIGINS` includes the extension origin shown by Chrome.

## API surface

| Method | Path | Authentication | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/auth/google-login` | None | Exchange a Google OAuth2 access token for a TruthLens JWT. |
| `POST` | `/api/verify` | Bearer JWT | Verify an AI-generated answer. |
| `GET` | `/api/history` | Bearer JWT | Read paginated history for the authenticated user. |
| `GET` | `/api/health` | None | Check backend availability. |
| `GET` | `/api/analytics/stats` | Optional JWT | Read verification statistics. |
| `GET` | `/api/analytics/history` | Optional JWT | Read analytics events. |
| `GET` | `/api/analytics/preprocessing` | Optional JWT | Read preprocessing metrics. |
| `GET` | `/api/analytics/pipeline` | Optional JWT | Read stage-latency metrics. |
| `DELETE` | `/api/analytics/clear` | Optional JWT | Clear analytics events. |

For request and response details, see the [API testing guide](MD%20files/API_TESTING.md) or use the generated OpenAPI docs at `/docs`.

## Project layout

```text
AI-Hallucination-Risk-Assessment/
├── main.py                         # FastAPI application and lifecycle setup
├── requirements.txt                # Python dependencies
├── .env.example                    # Configuration template
├── Dockerfile                      # Backend image
├── docker-compose.yml              # Backend + Redis development stack
├── app/
│   ├── api/routes/                 # Auth, verification, and analytics routes
│   ├── core/                       # Settings, auth, cache, HTTP client, limiter
│   ├── db/                         # MongoDB connection and history repository
│   ├── models/                     # Pydantic request, response, and history models
│   └── services/
│       ├── preprocessing/          # Claim extraction and query classification
│       ├── retrieval/              # Evidence source adapters and router
│       └── judge/                  # LLM judge and source-consensus mediator
├── chrome-extension/               # Manifest V3 extension
├── dashboard/                      # Basic dashboard static files
├── analytics-dashboard/            # Detailed analytics static files
├── tests/                          # pytest test suite
└── MD files/                       # Project-specific setup and design notes
```

## Configuration

All settings are loaded from `.env` using Pydantic Settings. The most important variables are:

| Variable | Purpose |
| --- | --- |
| `LLM_PROVIDER` | `groq`, `gemini`, `openai`, `grok`, or `anthropic`. |
| `LLM_API_KEY` | API key for the selected LLM provider. |
| `LLM_MODEL` | Model name passed to the selected provider. |
| `SERPAPI_KEY` | Enables SerpAPI-backed retrieval; optional. |
| `REDIS_URL` / `REDIS_ENABLED` | Redis cache connection and toggle. |
| `MONGODB_URL` / `DATABASE_NAME` | MongoDB connection and database name. |
| `JWT_SECRET` / `JWT_ALGORITHM` | Verification token signing configuration. |
| `ALLOWED_ORIGINS` | Comma-separated or JSON list of permitted browser origins. |
| `MAX_CLAIMS_PER_REQUEST` | Maximum number of extracted claims; defaults to 3. |

Never commit `.env` or provider credentials. Use `.env.example` as the starting point for local configuration.

## Testing

Run the test suite from the project directory with an activated virtual environment:

```bash
python -m pytest -q
```

The tests cover request/response models, preprocessing, retrieval adapters, judge behavior, authentication and history, analytics, endpoint security, rate limiting, and CORS behavior.

## Documentation and help

- [Quick start and environment reference](MD%20files/QUICKSTART.md)
- [API testing examples](MD%20files/API_TESTING.md)
- [Architecture notes](MD%20files/ARCHITECTURE.md)
- [Verification behavior](MD%20files/VERIFICATION.md)
- [SerpAPI setup notes](MD%20files/SERPAPI_SETUP.md)
- [GitHub Issues](https://github.com/MaNaa04/Truthlens-AI/issues) for bugs, questions, and feature requests

When reporting a problem, include the endpoint or extension flow involved, the relevant log message, your Python version, and a redacted description of your configuration. Do not include API keys or JWTs.

## Maintainers and contributions

TruthLens is maintained by [Manas Pawar](https://github.com/MaNaa04).

Contributions are welcome. For a focused change:

1. Open an issue for substantial behavior changes or new integrations.
2. Create a branch and keep the change scoped to one concern.
3. Add or update tests for backend behavior.
4. Run `python -m pytest -q` before opening a pull request.
5. Describe configuration, API, or extension changes clearly in the pull request.
