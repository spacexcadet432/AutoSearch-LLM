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
  "api_key": "sk-..."
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

You can also pass OpenAI key through header:
`X-OpenAI-API-Key: sk-...`

## Security Notes

- OpenAI key can be sent per request from frontend.
- Backend uses key only for the current request.
- Key is not persisted or logged by app code.

## Local Setup

### 1) Backend

```bash
pip install -r requirements.txt
```

Create `.env`:
```bash
SERPER_API_KEY=your_serper_key
# OPENAI_API_KEY is optional when frontend sends api_key per request
OPENAI_API_KEY=optional_default_key
```

Run:
```bash
uvicorn backend.main:app --reload
```

### 2) Frontend (Next.js)

```bash
cd frontend
npm install
```

Create `frontend/.env.local`:
```bash
NEXT_PUBLIC_BACKEND_URL=http://localhost:8000
```

Run:
```bash
npm run dev
```

## Deployment

### Backend (Railway / Render / Fly.io)

Start command:
```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

Required env vars:
- `SERPER_API_KEY`
- `OPENAI_API_KEY` (optional fallback if frontend does not send key)

### Render (Backend + Frontend together)

- This repo includes `render.yaml` for a Render Blueprint deployment.
- In Render, create a new Blueprint and point to this repository.
- Set environment variables in Render dashboard:
  - Backend: `SERPER_API_KEY`, optional `OPENAI_API_KEY`
  - Frontend: `NEXT_PUBLIC_BACKEND_URL` (set to your backend Render URL)
- Backend start command is already configured as:
  - `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

### Frontend (Vercel)

- Import `frontend/` as Vercel project.
- Set env var:
  - `NEXT_PUBLIC_BACKEND_URL=https://<your-backend-domain>`

## Recruiter Demo Highlights

- Adaptive LLM + retrieval routing
- Real-time grounding with source citations
- Async scraping and ranking
- Per-request API key handling
- Full-stack app with deployable frontend/backend split
