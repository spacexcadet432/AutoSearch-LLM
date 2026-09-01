"""Retrieval failure-mode tests: partial failure, total failure, cancellation, concurrency."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.services.search import retrieve_sources
from tests.conftest import RICH_TEXT, html_page, make_candidates


async def _run(stats=None, **kwargs):
    return await retrieve_sources(
        "what is the current price of something",
        serper_api_key="test-key",
        stats=stats,
        **kwargs,
    )


# ---------------------------------------------------------------- happy path
async def test_successful_retrieval_returns_ranked_sources(fake_discover, fake_fetch):
    fake_discover(make_candidates(3))

    async def handler(url):
        return html_page(RICH_TEXT)

    fake_fetch(handler)

    stats: dict = {}
    results = await _run(stats)

    assert results, "expected retrieved sources"
    assert stats["status"] == "ok"
    assert stats["failed_pages"] == 0
    assert all(r["url"] and r["chunk_text"] for r in results)


# ------------------------------------------------------- one source fails
async def test_one_failing_source_does_not_kill_the_others(fake_discover, fake_fetch):
    candidates = make_candidates(3)
    fake_discover(candidates)
    failing = candidates[0]["url"]

    async def handler(url):
        if url == failing:
            raise httpx.ConnectError("connection refused")
        return html_page(RICH_TEXT)

    fake_fetch(handler)

    stats: dict = {}
    results = await _run(stats)

    assert results, "surviving sources must still produce results"
    assert failing not in {r["url"] for r in results}
    assert stats["status"] == "partial"
    assert stats["failed_pages"] >= 1
    outcomes = {o["outcome"] for o in stats["page_outcomes"]}
    assert "fetch_error" in outcomes


async def test_partial_retrieval_reports_partial_status(fake_discover, fake_fetch):
    candidates = make_candidates(3)
    fake_discover(candidates)
    ok_url = candidates[2]["url"]

    async def handler(url):
        if url != ok_url:
            raise httpx.ReadTimeout("too slow")
        return html_page(RICH_TEXT)

    fake_fetch(handler)

    stats: dict = {}
    results = await _run(stats)

    assert {r["url"] for r in results} >= {ok_url}
    assert stats["status"] == "partial"


# ------------------------------------------------------- all sources fail
async def test_all_sources_failing_degrades_to_snippets(fake_discover, fake_fetch):
    """Every fetch fails, but Serper snippets still give us usable sources."""
    fake_discover(make_candidates(4))

    async def handler(url):
        raise httpx.ConnectError("dns failure")

    fake_fetch(handler)

    stats: dict = {}
    results = await _run(stats)

    assert results, "should degrade to snippets rather than returning nothing"
    assert stats["degraded_to_snippets"] is True
    assert stats["status"] == "partial"
    assert stats["failure_reason"] == "all_fetches_failed_used_snippets"


async def test_all_sources_fail_and_no_snippets_returns_nothing(fake_discover, fake_fetch):
    """With no usable snippets either, retrieval honestly reports no results."""
    fake_discover(make_candidates(3, snippet=""))

    async def handler(url):
        raise httpx.ConnectError("dns failure")

    fake_fetch(handler)

    stats: dict = {}
    results = await _run(stats)

    assert results == []
    assert stats["status"] == "no_results"
    assert stats["failure_reason"] == "no_extractable_content"


# ------------------------------------------------------------- timeouts
async def test_page_timeout_is_an_expected_failure(fake_discover, fake_fetch):
    fake_discover(make_candidates(2))

    async def handler(url):
        raise asyncio.TimeoutError()

    fake_fetch(handler)

    stats: dict = {}
    await _run(stats)
    outcomes = {o["outcome"] for o in stats["page_outcomes"]}
    assert outcomes == {"fetch_error"}


async def test_slow_pages_are_bounded_by_the_deadline(fake_discover, fake_fetch):
    """A slow source must not extend the request beyond the retrieval deadline."""
    fake_discover(make_candidates(2))

    async def handler(url):
        await asyncio.sleep(10)
        return html_page(RICH_TEXT)

    fake_fetch(handler)

    started = asyncio.get_running_loop().time()
    stats: dict = {}
    results = await _run(stats, deadline_ms=400)
    elapsed = asyncio.get_running_loop().time() - started

    # The 10s pages must not extend the request: the deadline cuts them off.
    assert elapsed < 5, f"deadline not enforced, took {elapsed:.1f}s"
    # No page produced content, so retrieval degrades to snippets rather than
    # failing the request outright.
    assert stats["degraded_to_snippets"] is True
    assert all(r["chunk_text"] for r in results)


# ----------------------------------------------------------- cancellation
async def test_cancellation_leaves_no_orphan_tasks(fake_discover, fake_fetch):
    """Client disconnect must not leave fetch tasks running after the request."""
    fake_discover(make_candidates(3))

    async def handler(url):
        await asyncio.sleep(30)
        return html_page(RICH_TEXT)

    fake_fetch(handler)

    task = asyncio.create_task(_run(deadline_ms=20000))
    await asyncio.sleep(0.2)
    assert not task.done()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await asyncio.sleep(0.1)
    orphans = [
        t for t in asyncio.all_tasks()
        if t is not asyncio.current_task()
        and not t.done()
        and "fetch_one" in getattr(t.get_coro(), "__qualname__", "")
    ]
    assert orphans == [], f"orphaned fetch tasks survived cancellation: {orphans}"


# ------------------------------------------------------ bounded concurrency
async def test_fetch_concurrency_is_bounded(monkeypatch, fake_discover, fake_fetch):
    monkeypatch.setenv("AUTOSEARCH_FETCH_CONCURRENCY", "2")
    fake_discover(make_candidates(6))

    in_flight = 0
    peak = 0

    async def handler(url):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.05)
            return html_page(RICH_TEXT)
        finally:
            in_flight -= 1

    fake_fetch(handler)

    await _run(max_pages=6, deadline_ms=5000)
    assert peak <= 2, f"concurrency limit exceeded: peak={peak}"


# --------------------------------------------------- malformed / empty input
@pytest.mark.parametrize(
    "payload",
    ["", "   ", "<html>", "\x00\x01\x02 binary junk", "<html><body></body></html>"],
)
async def test_malformed_pages_do_not_crash_retrieval(fake_discover, fake_fetch, payload):
    fake_discover(make_candidates(2))

    async def handler(url):
        return payload

    fake_fetch(handler)

    stats: dict = {}
    results = await _run(stats)  # must not raise
    assert isinstance(results, list)
    assert stats["status"] in {"ok", "partial", "no_results"}


async def test_empty_search_results(fake_discover):
    fake_discover([])
    stats: dict = {}
    assert await _run(stats) == []
    assert stats["status"] == "no_results"
    assert stats["failure_reason"] == "no_search_results"


async def test_search_provider_failure_returns_no_sources(fake_discover):
    from backend.services.errors import SearchProviderError

    fake_discover(SearchProviderError("boom", retryable=False, status_code=401))
    stats: dict = {}
    assert await _run(stats) == []
    assert stats["status"] == "failed"
    assert stats["failure_reason"] == "search_provider_error"


# ------------------------------------------- unexpected errors stay visible
async def test_unexpected_error_is_logged_not_silently_swallowed(
    fake_discover, fake_fetch, caplog
):
    """A programming error must be logged with a traceback, not disguised."""
    fake_discover(make_candidates(2))

    async def handler(url):
        raise AttributeError("this is a bug, not a network failure")

    fake_fetch(handler)

    stats: dict = {}
    with caplog.at_level("ERROR"):
        await _run(stats)

    outcomes = {o["outcome"] for o in stats["page_outcomes"]}
    assert outcomes == {"unexpected_error"}
    assert any("unexpected error fetching" in r.message for r in caplog.records)
    assert any(r.exc_info for r in caplog.records), "expected a traceback"
