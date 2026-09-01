# Caching (Phase 3)

## What is cached

**Only Serper search discovery results** — the list of `{url, title, snippet}` candidates for a
query. This is the single most expensive external operation in the request path: the Phase 1
baseline measured Serper discovery at **~2.02 s mean**, against a 3.5 s retrieval budget.

The cache sits inside `discover_urls()`, so the flow is:

```
Query → Router → discover_urls → cache HIT  → reuse candidates
                              └→ cache MISS → Serper → store → continue pipeline
```

Everything downstream (page fetching, extraction, ranking, generation) runs normally on both
paths. Routing is untouched and runs before the cache is consulted, so caching **cannot change
routing behaviour**.

## What is NOT cached, and why

- **Generated LLM answers.** Grounded answers are derived from live page content fetched at
  request time; caching them would let a stale answer outlive the sources it claims to be
  grounded in, which would undo the Phase 2 grounding-honesty work. Answers also vary with
  retrieval outcome (`grounded`, `retrieval_status`), so a cached answer could misreport its
  own provenance.
- **Failed searches.** A failure is never stored — the next request retries for real.
- **Empty results.** Caching a zero-result response would pin a transient outage for the whole
  TTL.
- **Router decisions.** Routing is one short LLM call and was not the bottleneck. Caching it
  would add invalidation risk for little gain.
- **Anything user-specific.** The API key is deliberately excluded from the cache key. Search
  results are not user-specific, so entries are shared safely across callers, and credentials
  never reach a cache.

## Cache key

`sha256(normalised_query | k | gl | hl)`

The query is whitespace-collapsed and case-folded, so `"Current  Bitcoin   Price"` and
`"current bitcoin price"` share one entry. `k` is part of the key, so a request for more
results never reuses a shorter list.

## Expiry and bounds

- **TTL**: entries expire 300 s after being written. Expired entries are deleted on read and
  purged in bulk before eviction, so they are never served.
- **Bound**: at most 256 entries. On overflow, expired entries are purged first, then the
  least-recently-used entry is evicted.
- Reads move an entry to the most-recently-used position (LRU).

## Configuration

| Setting | Default | Env var |
|---|---|---|
| Enabled | `true` | `AUTOSEARCH_SEARCH_CACHE_ENABLED` |
| TTL (seconds) | `300` | `AUTOSEARCH_SEARCH_CACHE_TTL_S` |
| Max entries | `256` | `AUTOSEARCH_SEARCH_CACHE_MAX_ENTRIES` |

Malformed values fall back to the defaults. `backend.services.cache.reset_search_cache()`
flushes the cache and rebuilds it from current configuration.

## Observability

`TTLCache.stats()` reports `entries`, `hits`, `misses`, `hit_rate`, `evictions` and
`expirations`. Per-request, `retrieve_sources(stats=...)` sets `search_cache_hit`, so the
Phase 1 evaluation harness records cache behaviour alongside its latency numbers.

## Concurrency

The cache is a plain dict accessed only from the asyncio event loop. Neither `get` nor `set`
awaits, so no coroutine can interleave mid-operation and no lock is required.

**Known limitation — no single-flight.** Concurrent identical requests that all miss will each
call Serper, because they check the cache before any of them has a result to store. Results
stay correct and the cache stays consistent; only the duplicate calls are wasted. Request
coalescing would fix this and is a reasonable Phase 4 candidate.

Other limitations: the cache is **per-process** (multiple workers each keep their own, and it
is empty after a restart), and it is memory-only by design — no Redis, no external store.
