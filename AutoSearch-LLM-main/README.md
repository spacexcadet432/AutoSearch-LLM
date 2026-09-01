# AutoSearch-LLM

Adaptive LLM routing system that decides whether a query should be answered directly or grounded using live web retrieval.

## Architecture

`User Query -> Temporal Classifier -> (Direct Answer | Web Search + Scrape + Rank + Grounded Generation)`

Backend structure:

`backend/main.py`
- FastAPI app setup and middleware

`backend/routes/query.py`
- `POST /query` endpoint

`backend/services/routing.py`
- Temporal routing decision with confidence

`backend/services/search.py`
- URL discovery, deduplication, async scraping pipeline, ranking

`backend/services/scraper.py`
- HTML fetch + readability extraction

`backend/services/generator.py`
- Direct and grounded LLM generation

`backend/models/query.py`
- Request/response schemas

## API Contract

### `POST /query`

Request body:
```json
{
  "query": "What is the latest GPT-5 release timeline?",
  "openai_api_key": "sk-...",
  "serper_api_key": "serper-..."
}
```

Response:
```json
{
  "answer": "...",
  "used_search": true,
  "sources": ["https://..."],
  "latency": 2.184,
  "routing_decision": "search",
  "confidence": 0.91
}
```

You can also pass keys through headers:
`X-OpenAI-API-Key: sk-...`
`X-Serper-API-Key: serper-...`

## Reliability

Timeout, retry, degradation and error-handling behaviour is documented in
[`docs/RELIABILITY.md`](docs/RELIABILITY.md). Summary:

- Every external call is bounded (LLM 30 s, Serper 6 s, page fetch 3 s, retrieval stage 3.5 s),
  configurable via `AUTOSEARCH_*` environment variables.
- Serper retries once on transient failures only; auth/bad-request failures fail fast.
- Retrieval degrades rather than failing the request: page text -> search snippet -> direct answer.
- The response reports `retrieval_status` and `grounded` so an ungrounded answer is never
  presented as source-backed.
- Serper search results are cached in-process (bounded TTL cache, 300 s / 256 entries) -
  see [`docs/CACHING.md`](docs/CACHING.md). Generated answers are never cached.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The suite is fully offline - no API keys and no network calls.

## Security Notes (BYO Keys)

- Both OpenAI and Serper keys are required for each request.
- Keys are used only in request scope (in-memory), then discarded.
- Backend does not rely on server-side stored keys.
- Keys are not persisted or logged by app code.

## Local Setup

### 1) Backend

```bash
pip install -r requirements.txt
```

Run:
```bash
uvicorn backend.main:app --reload
```

### 2) Frontend (TanStack Start + Vite)

The UI lives in `frontend/` (TanStack Router / React Start).

```bash
cd frontend
npm install
```

Create `frontend/.env.local`:

```bash
VITE_PUBLIC_BACKEND_URL=http://localhost:8000
```

Run:

```bash
npm run dev
```

Build / production-style start:

```bash
npm run build
npm run start
```

The duplicate folder `New Frontend/` in the repo is the upstream Lovable export; **`frontend/` is the canonical app** wired to this backend.

## Deployment

### Backend (Railway / Render / Fly.io)

Start command:
```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Required env vars:
- none for LLM/search provider keys (BYO keys per request)

### Render (Backend + Frontend together)

- This repo includes `render.yaml` for a Render Blueprint deployment.
- In Render, create a new Blueprint and point to this repository.
- Set environment variables in Render dashboard:
  - Backend: no provider key env vars required
  - Frontend: `VITE_PUBLIC_BACKEND_URL` (your backend URL, e.g. `https://your-api.onrender.com` — no trailing slash)
- Backend start command is already configured as:
  - `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- Frontend uses Vite build + Node server: `npm run build` then `npm run start` (see `frontend/package.json`).

### Frontend (Vercel or similar)

- **Root Directory:** `frontend` (not `New Frontend`, not `adaptive-route-ai-main`).
- Install: `npm install`
- Build: `npm run build`
- Env: `VITE_PUBLIC_BACKEND_URL=https://<your-backend-domain>`

If the site loads but shows **404 / blank**: the app was using the Lovable **Cloudflare-only** Vite config without **Nitro’s Vercel preset**, so Vercel never received a valid full-stack output. This repo’s `frontend/vite.config.ts` now uses **TanStack Start + `nitro({ preset: "vercel" })`**, which is what Vercel expects for TanStack Start ([Vercel docs](https://vercel.com/docs/frameworks/full-stack/tanstack-start)).

- Optional: `frontend/vercel.json` sets install/build commands explicitly.

## Recruiter Demo Highlights

- Adaptive LLM + retrieval routing
- Real-time grounding with source citations
- Async scraping and ranking
- Per-request API key handling
- Full-stack app with deployable frontend/backend split
