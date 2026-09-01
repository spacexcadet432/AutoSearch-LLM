"""Search + retrieval service."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import httpx

from chunking import chunk_text
from ranker import CandidateChunk, domain_of, score_chunks, select_top_chunks

from backend.services import config
from backend.services.cache import get_search_cache, make_search_key
from backend.services.errors import PageFetchError, SearchProviderError
from backend.services.scraper import extract_main_text, fetch_html

SERPER_ENDPOINT = "https://google.serper.dev/search"
logger = logging.getLogger(__name__)

# Failures that are worth one more attempt: the request never reached a
# definitive answer, or the provider explicitly asked us to back off.
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

# Expected, non-bug failures when fetching a single candidate page.
_EXPECTED_FETCH_ERRORS = (
    PageFetchError,
    httpx.HTTPError,
    asyncio.TimeoutError,
    UnicodeDecodeError,
    ValueError,
)


def _truncate_words(text: str, max_words: int = 1200) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


async def _serper_request(
    query: str,
    *,
    serper_api_key: str,
    k: int,
    timeout_s: float,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """One Serper call. Raises SearchProviderError tagged with retryability.

    When ``client`` is supplied it is reused, so retry attempts share a single
    connection pool instead of repeating the TLS handshake.
    """
    payload: dict[str, Any] = {"q": query, "num": k, "gl": "us", "hl": "en"}
    headers = {"X-API-KEY": serper_api_key, "Content-Type": "application/json"}
    timeout = httpx.Timeout(timeout_s, connect=min(3.0, timeout_s))

    try:
        if client is not None:
            response = await client.post(SERPER_ENDPOINT, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=timeout, headers=headers) as owned:
                response = await owned.post(SERPER_ENDPOINT, json=payload)
    except httpx.TimeoutException as error:
        raise SearchProviderError("Search provider timed out.", retryable=True) from error
    except httpx.HTTPError as error:
        raise SearchProviderError("Search provider request failed.", retryable=True) from error

    if response.status_code != 200:
        # 401/403 (bad key) and 400 (bad request) will never succeed on retry;
        # retrying them only burns quota and delays the user's error.
        retryable = response.status_code in _RETRYABLE_STATUS
        raise SearchProviderError(
            f"Search provider error: {response.status_code}",
            retryable=retryable,
            status_code=response.status_code,
        )

    try:
        return response.json().get("organic", []) or []
    except ValueError as error:
        # 200 with a non-JSON body: treat as a transient provider glitch.
        raise SearchProviderError(
            "Search provider returned a malformed response.", retryable=True
        ) from error


async def discover_urls(
    query: str,
    *,
    serper_api_key: str,
    k: int = 8,
    max_attempts: int | None = None,
    timeout_s: float | None = None,
    use_cache: bool = True,
    cache_info: dict[str, Any] | None = None,
) -> list[dict[str, str | None]]:
    """Discover candidate URLs from Serper, retrying only transient failures.

    Results are served from a bounded TTL cache when available. Only successful,
    non-empty results are cached: failures must never be memoised, and caching an
    empty result would pin a transient zero-result outcome for the whole TTL.
    """
    attempts = max_attempts if max_attempts is not None else config.search_max_attempts()
    timeout = timeout_s if timeout_s is not None else config.search_timeout_s()
    base_delay = config.search_retry_base_delay_s()

    caching = use_cache and config.search_cache_enabled()
    cache = get_search_cache() if caching else None
    cache_key = make_search_key(query, k=k) if caching else None

    if cache is not None and cache_key is not None:
        hit, cached = cache.get(cache_key)
        if hit:
            logger.info("retrieval: search cache HIT")
            if cache_info is not None:
                cache_info["cache_hit"] = True
            # Copy so a caller mutating the list cannot corrupt the entry.
            return list(cached)
    if cache_info is not None:
        cache_info["cache_hit"] = False

    organic: list[dict[str, Any]] = []
    last_error: SearchProviderError | None = None

    # One client for every attempt: retries reuse the connection pool instead of
    # repeating the TLS handshake.
    timeout_cfg = httpx.Timeout(timeout, connect=min(3.0, timeout))
    async with httpx.AsyncClient(timeout=timeout_cfg) as client:
        for attempt in range(1, attempts + 1):
            try:
                organic = await _serper_request(
                    query,
                    serper_api_key=serper_api_key,
                    k=k,
                    timeout_s=timeout,
                    client=client,
                )
                break
            except SearchProviderError as error:
                last_error = error
                if not error.retryable or attempt >= attempts:
                    raise
                # Exponential backoff with jitter; bounded by max_attempts so
                # this can never become a retry storm.
                delay = base_delay * (2 ** (attempt - 1))
                delay += random.uniform(0, base_delay)
                logger.warning(
                    "retrieval: serper attempt %s/%s failed (%s); retrying in %.2fs",
                    attempt, attempts, error, delay,
                )
                await asyncio.sleep(delay)
        else:  # pragma: no cover - loop always breaks or raises
            if last_error:
                raise last_error

    deduped: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for item in organic:
        url = item.get("link")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(
            {"url": url, "title": item.get("title"), "snippet": item.get("snippet")}
        )
        if len(deduped) >= k:
            break

    if cache is not None and cache_key is not None and deduped:
        cache.set(cache_key, list(deduped))
    return deduped


async def retrieve_sources(
    query: str,
    *,
    serper_api_key: str,
    k_search: int = 6,
    top_m: int = 3,
    deadline_ms: int | None = None,
    max_pages: int = 3,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    End-to-end retrieval:
    search -> async scrape -> extraction -> chunking -> rank top chunks.

    Partial success is preserved: pages that fail are skipped, and whatever was
    successfully fetched within the deadline is still ranked and returned.

    If ``stats`` is provided it is populated in place with per-stage timings and
    counters for observability/evaluation. It never affects returned results.
    """
    deadline_ms = deadline_ms if deadline_ms is not None else config.retrieval_deadline_ms()
    start = time.monotonic()
    deadline_s = start + (deadline_ms / 1000.0)

    def record(**fields: Any) -> None:
        if stats is not None:
            stats.update(fields)

    record(
        failure_reason=None,
        status="failed",
        discovered_count=0,
        page_outcomes=[],
        pages_attempted=0,
    )

    discover_start = time.monotonic()
    cache_info: dict[str, Any] = {}
    try:
        all_candidates = await discover_urls(
            query, serper_api_key=serper_api_key, k=k_search, cache_info=cache_info
        )
    except SearchProviderError as error:
        record(
            discover_ms=round((time.monotonic() - discover_start) * 1000, 1),
            failure_reason="search_provider_error",
            status="failed",
            search_error=type(error).__name__,
            search_status_code=error.status_code,
        )
        logger.warning("retrieval: search provider unavailable (%s)", error)
        return []
    record(
        discover_ms=round((time.monotonic() - discover_start) * 1000, 1),
        search_cache_hit=cache_info.get("cache_hit", False),
    )
    if not all_candidates:
        record(failure_reason="no_search_results", status="no_results")
        return []

    # Fetch only max_pages, but keep the full candidate list so the snippet
    # fallback below still has spare sources when the fetched pages fail.
    candidates = all_candidates[:max_pages]
    logger.info("retrieval: discovered_candidates=%s", len(candidates))
    record(discovered_count=len(all_candidates), pages_attempted=len(candidates))

    page_outcomes: list[dict[str, Any]] = []
    fetch_start = time.monotonic()
    sem = asyncio.Semaphore(config.fetch_concurrency())
    fetch_timeout = config.fetch_timeout_s()
    max_bytes = config.max_download_bytes()

    async with httpx.AsyncClient() as client:
        async def fetch_one(candidate: dict[str, str | None]) -> list[CandidateChunk]:
            async with sem:
                if time.monotonic() >= deadline_s:
                    page_outcomes.append(
                        {"url": candidate.get("url"), "outcome": "deadline_exceeded"}
                    )
                    return []
                try:
                    html = await fetch_html(
                        candidate["url"],
                        client=client,
                        timeout_s=fetch_timeout,
                        max_bytes=max_bytes,
                    )
                    text = _truncate_words(extract_main_text(html), max_words=1000)
                    outcome = "extracted"
                    if len(text) < 220:
                        snippet = (candidate.get("snippet") or "").strip()
                        title = (candidate.get("title") or "").strip()
                        if len(snippet) < 60:
                            page_outcomes.append(
                                {
                                    "url": candidate.get("url"),
                                    "outcome": "thin_content",
                                    "text_len": len(text),
                                }
                            )
                            return []
                        text = f"{title}\n\n{snippet}".strip()
                        outcome = "snippet_fallback"

                    logger.info(
                        "retrieval: source_text_length=%s url=%s",
                        len(text),
                        candidate.get("url"),
                    )
                    chunks = [
                        CandidateChunk(
                            url=candidate["url"],
                            title=candidate.get("title"),
                            snippet=candidate.get("snippet"),
                            chunk_text=chunk,
                            chunk_index=idx,
                        )
                        for idx, chunk in enumerate(
                            chunk_text(
                                text,
                                max_chars=1200,
                                overlap_paragraphs=0,
                                min_chunk_chars=120,
                            )
                        )
                    ]
                    if chunks:
                        page_outcomes.append(
                            {
                                "url": candidate.get("url"),
                                "outcome": outcome,
                                "text_len": len(text),
                                "chunks": len(chunks),
                            }
                        )
                        return chunks
                    page_outcomes.append(
                        {
                            "url": candidate.get("url"),
                            "outcome": outcome,
                            "text_len": len(text),
                            "chunks": 1,
                        }
                    )
                    return [
                        CandidateChunk(
                            url=candidate["url"],
                            title=candidate.get("title"),
                            snippet=candidate.get("snippet"),
                            chunk_text=text[:900],
                            chunk_index=0,
                        )
                    ]
                except asyncio.CancelledError:
                    # Never swallow cancellation: it must propagate so the task
                    # actually stops when the caller goes away.
                    raise
                except _EXPECTED_FETCH_ERRORS as error:
                    page_outcomes.append(
                        {
                            "url": candidate.get("url"),
                            "outcome": "fetch_error",
                            "error": type(error).__name__,
                        }
                    )
                    return []
                except Exception as error:  # noqa: BLE001 - deliberate: see below
                    # An unexpected exception here is a bug, not a network fact.
                    # Log it with a traceback so it stays visible, but still
                    # degrade gracefully so one broken page cannot fail the
                    # whole request.
                    logger.exception(
                        "retrieval: unexpected error fetching %s", candidate.get("url")
                    )
                    page_outcomes.append(
                        {
                            "url": candidate.get("url"),
                            "outcome": "unexpected_error",
                            "error": type(error).__name__,
                        }
                    )
                    return []

        tasks = [asyncio.create_task(fetch_one(c)) for c in candidates if c.get("url")]
        if not tasks:
            record(failure_reason="no_fetchable_urls", status="failed")
            return []

        pending: set[asyncio.Task[list[CandidateChunk]]] = set(tasks)
        all_chunks: list[CandidateChunk] = []
        unique_urls: set[str] = set()

        try:
            while pending and time.monotonic() < deadline_s:
                remaining = max(0.0, deadline_s - time.monotonic())
                completed, pending = await asyncio.wait(
                    pending,
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not completed:
                    break

                for task in completed:
                    if task.cancelled():
                        continue
                    error = task.exception()
                    if error is not None:
                        # fetch_one handles its own errors, so this means an
                        # unexpected escape. Log it rather than crashing the
                        # whole retrieval.
                        logger.error(
                            "retrieval: fetch task raised unexpectedly: %r", error
                        )
                        continue
                    page_chunks = task.result()
                    all_chunks.extend(page_chunks)
                    for chunk in page_chunks:
                        unique_urls.add(chunk.url)

                # Early exit once we have enough context from at least two sources.
                if len(unique_urls) >= 2 and len(all_chunks) >= 3:
                    break
        finally:
            # Always reachable, including when the caller is cancelled (client
            # disconnect). Without this, in-flight fetch tasks outlived the
            # request and kept running against a closed HTTP client.
            leftover = [t for t in tasks if not t.done()]
            for task in leftover:
                task.cancel()
            if leftover:
                await asyncio.gather(*leftover, return_exceptions=True)

    record(
        fetch_ms=round((time.monotonic() - fetch_start) * 1000, 1),
        page_outcomes=page_outcomes,
        pages_yielding_chunks=len({c.url for c in all_chunks}),
        chunks_extracted=len(all_chunks),
    )

    degraded_to_snippets = False
    if not all_chunks:
        # Every fetched page failed. Rather than losing the request entirely,
        # fall back to the search snippets: they are real text from the same
        # URLs, and the thin-content path above already treats them as a valid
        # source. Measured in Phase 1 as the cause of 3/15 total failures.
        snippet_chunks = [
            CandidateChunk(
                url=candidate["url"],
                title=candidate.get("title"),
                snippet=candidate.get("snippet"),
                chunk_text=(
                    f"{(candidate.get('title') or '').strip()}\n\n"
                    f"{(candidate.get('snippet') or '').strip()}"
                ).strip(),
                chunk_index=0,
            )
            for candidate in all_candidates
            if candidate.get("url") and len((candidate.get("snippet") or "").strip()) >= 60
        ]
        if not snippet_chunks:
            record(failure_reason="no_extractable_content", status="no_results")
            return []
        logger.warning(
            "retrieval: all %s page fetches failed; degrading to %s search snippets",
            len(candidates), len(snippet_chunks),
        )
        all_chunks = snippet_chunks
        degraded_to_snippets = True
        record(failure_reason="all_fetches_failed_used_snippets")

    rank_start = time.monotonic()
    scored = score_chunks(query, all_chunks)
    selected = select_top_chunks(scored, top_m=top_m, max_chunks_per_domain=1)
    if len({chunk.url for chunk in selected}) < 2:
        seen_urls = {chunk.url for chunk in selected}
        for _, candidate in scored:
            if candidate.url in seen_urls:
                continue
            selected.append(candidate)
            seen_urls.add(candidate.url)
            if len(seen_urls) >= 2 or len(selected) >= top_m:
                break
        if len(seen_urls) < 2:
            # Fall back across ALL discovered candidates, not just the subset we
            # attempted to fetch, so a second source is still offered when the
            # fetched pages failed.
            for candidate in all_candidates:
                url = candidate.get("url")
                snippet = (candidate.get("snippet") or "").strip()
                if not url or url in seen_urls or len(snippet) < 60:
                    continue
                selected.append(
                    CandidateChunk(
                        url=url,
                        title=candidate.get("title"),
                        snippet=candidate.get("snippet"),
                        chunk_text=snippet,
                        chunk_index=0,
                    )
                )
                seen_urls.add(url)
                if len(seen_urls) >= 2:
                    break

    # Distinguish full success from partial success so the caller can be honest
    # about how well-grounded the answer is.
    failed_pages = sum(
        1
        for outcome in page_outcomes
        if outcome.get("outcome")
        in {"fetch_error", "unexpected_error", "thin_content", "deadline_exceeded"}
    )
    record(
        rank_ms=round((time.monotonic() - rank_start) * 1000, 1),
        top_scores=[round(float(s), 4) for s, _ in scored[:10]],
        selected_count=len(selected),
        selected_unique_urls=len({c.url for c in selected}),
        selected_unique_domains=len({domain_of(c.url) for c in selected}),
        failed_pages=failed_pages,
        degraded_to_snippets=degraded_to_snippets,
        status="partial" if (failed_pages or degraded_to_snippets) else "ok",
        total_ms=round((time.monotonic() - start) * 1000, 1),
    )

    logger.info(
        "retrieval: scraped_sources=%s chunks_for_llm=%s",
        len({chunk.url for chunk in all_chunks}),
        len(selected),
    )
    results = [
        {
            "url": item.url,
            "title": item.title,
            "snippet": item.snippet,
            "chunk_text": item.chunk_text,
            "chunk_index": item.chunk_index,
        }
        for item in selected
    ]
    return results
