# Reliability (Phase 2)

How AutoSearch-LLM behaves when external dependencies misbehave. The architecture is
unchanged — routing → optional retrieval → generation. This documents the guardrails
around that path.

## Failure-mode inventory

| # | Failure | Behaviour before | Behaviour now |
|---|---|---|---|
| 1 | LLM API timeout | **600 s** read timeout, 2 SDK retries → a request could hang ~30 min | Bounded 30 s timeout (configurable); maps to `504` |
| 2 | LLM API error | Only `AuthenticationError` mapped; everything else → generic `500` | Explicit mapping: 401 / 429 / 502 / 504 |
| 3 | Serper failure | Single attempt, no retry | 1 bounded retry for transient failures only; non-retryable fail fast |
| 4 | Page fetch timeout | Caught, source dropped | Same, plus recorded as `fetch_error` in stats |
| 5 | Non-HTML content (PDF/image) | Fed to the HTML parser as garbage | Rejected by content-type check |
| 6 | Extraction failure | Could raise `lxml.ParserError` out of the fallback path | Extraction is total: returns `""`, never raises |
| 7 | One source fails, others succeed | Survivors used | Unchanged (verified by test) + `status="partial"` |
| 8 | Cancellation during retrieval | **Orphaned tasks** kept running against a closed client | `finally` block cancels and awaits every in-flight task |
| 9 | Malformed LLM routing JSON | Defaulted to `direct`, confidence 0.7 | Unchanged (already safe) |
| 10 | Empty search results | Returned `[]` → ungrounded answer | Same, but reported as `retrieval_status="no_results"` |
| 11 | Rate limit (429) | Generic `500` | LLM → `429`; Serper → retried once, then degrades |
| 12 | Unexpected exception in fetch | Silently reported as `fetch_error` | Logged **with traceback** as `unexpected_error`; still degrades |
| 13 | All page fetches fail | Returned nothing (**3/15 queries in the Phase 1 run**) | Degrades to Serper snippets from the same URLs |
| 14 | Client disconnect | Task leak (see #8) | Cleanly cancelled |

## Timeout policy

**No external operation waits forever.** Every bound lives in
[`backend/services/config.py`](../backend/services/config.py) and is environment-overridable.

| Operation | Default | Env var |
|---|---|---|
| LLM request (read) | 30 s | `AUTOSEARCH_LLM_TIMEOUT_S` |
| LLM connect | 5 s | `AUTOSEARCH_LLM_CONNECT_TIMEOUT_S` |
| Serper request | 6 s | `AUTOSEARCH_SEARCH_TIMEOUT_S` |
| Single page fetch | 3 s | `AUTOSEARCH_FETCH_TIMEOUT_S` |
| Whole retrieval stage | 3500 ms | `AUTOSEARCH_RETRIEVAL_DEADLINE_MS` |
| Page fetch concurrency | 4 | `AUTOSEARCH_FETCH_CONCURRENCY` |
| Max download size | 1.5 MB | `AUTOSEARCH_MAX_DOWNLOAD_BYTES` |

A malformed value (`""`, `"abc"`, `"-5"`, `"0"`) falls back to the safe default — a typo can
never disable a timeout.

The retrieval deadline is a **wall-clock budget for the whole stage**, so slow pages are
abandoned rather than extending the request.

## Retry policy

Retries are deliberately narrow. Nothing retries blindly.

**LLM** — delegated to the OpenAI SDK (`max_retries`, default 2), which already retries only
connection errors, timeouts, 408/409/429 and 5xx with exponential backoff + jitter, and never
retries 400/401/403/404. Reimplementing that would add risk without adding value.

**Serper** — 1 retry (2 attempts total) with exponential backoff + jitter, applied *only* to:
- timeouts and connection errors
- 408, 409, 425, 429, 500, 502, 503, 504
- HTTP 200 with an unparseable body

Never retried: **400** (bad request) and **401/403** (bad key) — these cannot succeed on
retry and would only burn quota and delay the user's error.

**Page fetches are never retried.** With a 3.5 s stage budget and 3 candidate pages, a retry
would consume the budget that a *different* source could use more productively.

Retry budgets are bounded by `max_attempts`, so retry storms are structurally impossible.

## Degradation and grounding honesty

Retrieval failure degrades; it does not fail the request. The ladder:

1. Extract page text (preferred)
2. Page thin/unparseable → use that URL's search snippet
3. **All** fetches failed → use snippets from all discovered candidates
4. No usable snippets → answer from model knowledge, no sources

The response now distinguishes these states via two fields (both optional, so existing
clients are unaffected):

- `retrieval_status`: `ok` | `partial` | `no_results` | `no_useful_results` | `failed` | `null`
- `grounded`: `true` **only** when the answer was generated from retrieved sources

> The important case: when grounded generation reports *"insufficient verified information"*,
> the system falls back to an ungrounded answer. Previously that answer was returned with
> `used_search: true` and a list of sources, implying it was source-backed when it was model
> recall. It is now returned with `grounded: false`. **Unsupported information is never
> presented as sourced.**

## Error handling

- Expected external failures are caught by **specific** type and mapped to specific status codes.
- Unexpected exceptions are logged with a full traceback (`logger.exception`) so bugs stay
  visible, then surfaced as a generic `500`.
- Response bodies carry short fixed messages only — never provider text, stack traces, or key
  fragments. Provider error strings can embed request URLs and org ids, so they are logged
  server-side and never returned.

| Condition | Status |
|---|---|
| Missing API keys | 400 |
| Query too short | 422 |
| Invalid LLM key | 401 |
| LLM rate limited | 429 |
| LLM unreachable / rejected | 502 |
| LLM timeout | 504 |
| Retrieval unavailable | 503 |
| Unexpected error | 500 |

## Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

91 tests, ~3 seconds. **No API keys, no network** — every external service is faked, so the
suite is safe to run against zero remaining API quota.

Coverage: successful retrieval, single-source failure, total failure, timeouts, deadline
enforcement, retry policy and its bounds, cancellation/task-leak, malformed and binary pages,
empty search results, LLM failures, partial retrieval, bounded concurrency, fallback
behaviour, and error-response safety.

## Known limitations

- **Generation is not retried at the pipeline level.** If grounded generation raises, the
  request fails rather than silently substituting an ungrounded answer. This is deliberate:
  masking it would be the same dishonesty as #13 above.
- **No circuit breaker.** A persistently failing Serper is retried once per request. Fine at
  this scale; a breaker would help under sustained load.
- **No per-request global deadline.** Stages are individually bounded (worst case ≈ routing
  30 s + retrieval 3.5 s + generation 30 s), but there is no single overall cap.
- **Router failure fails the request.** If the classifier call fails after retries, the request
  errors rather than guessing a route. Guessing `direct` risks stale answers; guessing `search`
  costs money on a query that may not need it.
- **`retrieval_status`/`grounded` are not yet surfaced in the frontend.** The API reports them;
  the UI does not display them.
- **Reliability behaviour is verified by mocks, not live fault injection.** The Phase 1 live
  numbers informed which failures were worth fixing, but the fixes themselves are proven
  deterministically rather than against the real web.
