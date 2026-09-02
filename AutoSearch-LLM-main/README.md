# AutoSearch-LLM

A local command-line AI system that decides, per query, whether to answer from the
model's own knowledge or to ground the answer in live web results.

Ask *"What is the capital of France?"* and it answers directly. Ask *"What is the
current price of Bitcoin?"* and it searches the web, fetches and extracts the
pages, ranks the passages, and answers from those sources — telling you which
sources it used and whether the answer is actually grounded in them.

## Architecture

```
User
 ↓
CLI  (autosearch/cli.py)
 ↓
Query Router          — one LLM call: does this need fresh data?
 ↓
Serper / Retrieval    — search → fetch → extract → chunk → rank   (cached)
 ↓
Amazon Bedrock        — grounded generation from the retrieved passages
 ↓
Grounded Answer       — with sources and an explicit grounded/ungrounded flag
```

## Requirements

- **Python 3.11+**
- **An LLM credential** — an Amazon Bedrock API key (recommended) or an OpenAI key
- **A Serper API key** — free tier at [serper.dev](https://serper.dev)

No Docker, Node.js, database, or cloud account beyond those two API credentials.

## Installation

```bash
git clone <repo-url>
cd AutoSearch-LLM

python -m venv .venv
```

Activate it:

```bash
# Windows (PowerShell)
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate
```

Then:

```bash
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Edit `.env` and fill in your two credentials.

## Configuration

All configuration is environment variables, loaded from `.env`. `.env` is
gitignored — **never commit credentials**.

| Variable | Required | Purpose |
|---|---|---|
| `SERPER_API_KEY` | yes | Web search |
| `AWS_BEARER_TOKEN_BEDROCK` | yes* | Amazon Bedrock credential |
| `AUTOSEARCH_LLM_BASE_URL` | yes* | Bedrock endpoint, e.g. `https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1` |
| `AUTOSEARCH_LLM_MODEL` | yes* | e.g. `openai.gpt-oss-120b-1:0` |

\* Or use plain OpenAI instead: set `OPENAI_API_KEY`, leave `AUTOSEARCH_LLM_BASE_URL`
unset, and set `AUTOSEARCH_LLM_MODEL=gpt-4o-mini`.

> Bedrock's OpenAI-compatible API serves only the `openai.gpt-oss-*` models.
> Nova/Claude/Llama need Bedrock's native API, which this project does not use.

Optional tuning (timeouts, retries, cache) is listed in `.env.example` with
defaults in [`backend/services/config.py`](backend/services/config.py).

Check your setup without spending any API quota:

```bash
python -m autosearch --check
```

It names the exact variable that is missing rather than raising a stack trace.

## Running

```bash
python -m autosearch
```

One-shot mode (useful for scripting):

```bash
python -m autosearch "What is the latest stable Python release?"
python -m autosearch -v "..."     # show routing/retrieval/cache logs
```

## Example

```
$ python -m autosearch

AutoSearch-LLM ready.
Type a query, or 'exit' to quit.

Enter query:
> What is the latest stable release version of Python?

Routing:   web retrieval  (confidence 0.95)
Retrieval: ok - all sources retrieved
Sources:   2
  [1] https://www.python.org/downloads/
  [2] https://devguide.python.org/versions/
Grounded:  yes - answer generated from the sources above
Latency:   4.21s

Answer:
...

Enter query:
> exit
Bye.
```

Type `exit`, `quit`, or press Ctrl+C to leave. Multiple queries in one session
share the search cache.

## Evaluation

A reproducible evaluation harness with a hand-labelled 44-query dataset:

```bash
python -m evaluation.run_evaluation                  # all stages
python -m evaluation.run_evaluation --stages router  # router only
python -m evaluation.selftest                        # verify metric maths, offline
```

Results are written to `evaluation/results/`. Methodology, metrics and the
honest limitations are documented in [`evaluation/README.md`](evaluation/README.md).

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

The suite is **fully offline** — no API keys, no network, no quota consumed.

## Components

| Path | Role |
|---|---|
| `autosearch/cli.py` | Terminal interface (presentation only) |
| `backend/services/pipeline.py` | Orchestration: route → retrieve → generate |
| `backend/services/routing.py` | Temporal classifier |
| `backend/services/search.py` | Search, concurrent fetch, ranking, cache |
| `backend/services/scraper.py` | Page fetch + text extraction |
| `backend/services/generator.py` | Direct and grounded generation |
| `backend/services/cache.py` | Bounded TTL/LRU search cache |
| `backend/services/config.py` | All timeouts, retries and limits |
| `backend/main.py` | Optional FastAPI surface (not needed for the CLI) |
| `chunking.py`, `ranker.py` | Passage chunking and lexical ranking |

The CLI contains no retrieval or LLM logic — it calls the same pipeline the API
does.

## Reliability

Documented in [`docs/RELIABILITY.md`](docs/RELIABILITY.md) and
[`docs/CACHING.md`](docs/CACHING.md):

- **Bounded timeouts everywhere** — LLM 30 s (the SDK default is 600 s), Serper 6 s,
  page fetch 3 s, whole retrieval stage 3.5 s.
- **Bounded retries** — Serper retries once on transient failures only; auth and
  bad-request failures fail fast instead of burning quota.
- **Graceful degradation** — page text → search snippet → direct answer. A failed
  source never fails the request.
- **Honest grounding** — when retrieval does not support an answer, the result is
  marked ungrounded rather than presented as source-backed.
- **Clean cancellation** — Ctrl+C cancels in-flight fetches; no orphaned tasks.
- **Bounded search cache** — 300 s TTL, 256 entries, failures never cached.

Measured on a 15-query retrieval run, these changes took retrieval success from
**80% to 100%** (3 queries previously returned nothing). Latency was unchanged;
see `evaluation/results/` for the recorded numbers.

## Optional HTTP API

The FastAPI app is retained for programmatic use and is not required by the CLI:

```bash
uvicorn backend.main:app --reload    # POST /query, GET /health
```
