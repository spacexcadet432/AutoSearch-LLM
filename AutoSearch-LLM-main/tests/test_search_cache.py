"""Search discovery cache: hits, misses, TTL, bounds, and failure handling."""

from __future__ import annotations

import asyncio

import pytest

import backend.services.search as search
from backend.services.cache import TTLCache, get_search_cache, make_search_key
from backend.services.errors import SearchProviderError

ORGANIC = [
    {"link": "https://a.example.com", "title": "A", "snippet": "snippet a"},
    {"link": "https://b.example.com", "title": "B", "snippet": "snippet b"},
]


@pytest.fixture
def serper(monkeypatch):
    """Count Serper calls; optionally fail them."""
    calls = {"n": 0, "queries": []}

    def _install(outcome=ORGANIC):
        async def fake(query, *, serper_api_key, k, timeout_s, client=None):
            calls["n"] += 1
            calls["queries"].append(query)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(search, "_serper_request", fake)
        return calls

    return _install


async def _discover(query="what is the current price", **kw):
    return await search.discover_urls(query, serper_api_key="k", **kw)


# ------------------------------------------------------------ hit / miss
async def test_first_request_is_a_miss_and_calls_serper(serper):
    calls = serper()
    info: dict = {}
    results = await _discover(cache_info=info)

    assert calls["n"] == 1
    assert info["cache_hit"] is False
    assert [r["url"] for r in results] == ["https://a.example.com", "https://b.example.com"]
    assert get_search_cache().stats()["misses"] == 1


async def test_repeated_identical_request_is_a_hit(serper):
    calls = serper()
    first = await _discover()
    info: dict = {}
    second = await _discover(cache_info=info)

    assert calls["n"] == 1, "second identical request must not call Serper"
    assert info["cache_hit"] is True
    assert second == first
    assert get_search_cache().stats()["hits"] == 1


async def test_different_query_is_a_miss(serper):
    calls = serper()
    await _discover("query one")
    await _discover("query two")
    assert calls["n"] == 2


async def test_cache_never_serves_another_query_result(serper, monkeypatch):
    """A hit must return that query's own results, never a neighbour's."""
    async def fake(query, *, serper_api_key, k, timeout_s, client=None):
        return [{"link": f"https://{query}.example.com", "title": query, "snippet": "s"}]

    monkeypatch.setattr(search, "_serper_request", fake)

    a = await _discover("alpha")
    b = await _discover("beta")
    a_again = await _discover("alpha")

    assert a_again == a
    assert a_again != b
    assert a_again[0]["url"] == "https://alpha.example.com"


async def test_key_normalises_whitespace_and_case(serper):
    calls = serper()
    await _discover("Current  Bitcoin   Price")
    await _discover("current bitcoin price")
    assert calls["n"] == 1, "normalised variants should share one entry"


async def test_different_k_is_a_separate_entry(serper):
    calls = serper()
    await _discover("same query", k=4)
    await _discover("same query", k=8)
    assert calls["n"] == 2


# ------------------------------------------------------------------ TTL
async def test_expired_entry_is_a_miss_and_refetches(serper, monkeypatch):
    monkeypatch.setenv("AUTOSEARCH_SEARCH_CACHE_TTL_S", "0.05")
    from backend.services.cache import reset_search_cache

    reset_search_cache()
    calls = serper()

    await _discover()
    await asyncio.sleep(0.08)
    info: dict = {}
    await _discover(cache_info=info)

    assert calls["n"] == 2
    assert info["cache_hit"] is False
    assert get_search_cache().stats()["expirations"] >= 1


# -------------------------------------------------------------- failures
async def test_failed_search_is_not_cached(serper):
    """A failure must never be memoised: the next request retries for real."""
    calls = serper(SearchProviderError("down", retryable=False, status_code=500))

    for _ in range(2):
        with pytest.raises(SearchProviderError):
            await _discover()

    assert calls["n"] == 2, "failure was cached"
    assert len(get_search_cache()) == 0


async def test_empty_result_is_not_cached(serper):
    """Caching an empty result would pin a transient zero-result for the TTL."""
    calls = serper([])
    await _discover()
    await _discover()
    assert calls["n"] == 2
    assert len(get_search_cache()) == 0


async def test_recovery_after_failure_is_cached(serper, monkeypatch):
    state = {"fail": True, "n": 0}

    async def fake(query, *, serper_api_key, k, timeout_s, client=None):
        state["n"] += 1
        if state["fail"]:
            raise SearchProviderError("down", retryable=False)
        return ORGANIC

    monkeypatch.setattr(search, "_serper_request", fake)

    with pytest.raises(SearchProviderError):
        await _discover()
    state["fail"] = False
    await _discover()
    await _discover()

    assert state["n"] == 2, "success should be cached after an earlier failure"


# ---------------------------------------------------------------- bounds
async def test_cache_respects_max_entries(serper, monkeypatch):
    monkeypatch.setenv("AUTOSEARCH_SEARCH_CACHE_MAX_ENTRIES", "3")
    from backend.services.cache import reset_search_cache

    reset_search_cache()
    serper()

    for i in range(6):
        await _discover(f"query number {i}")

    cache = get_search_cache()
    assert len(cache) <= 3
    assert cache.stats()["evictions"] >= 3


async def test_least_recently_used_entry_is_evicted():
    cache = TTLCache(max_entries=2, ttl_s=60)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")          # 'a' becomes most-recently-used
    cache.set("c", 3)       # should evict 'b'

    assert cache.get("a")[0] is True
    assert cache.get("b")[0] is False
    assert cache.get("c")[0] is True


# ----------------------------------------------------------- concurrency
async def test_concurrent_identical_requests_are_safe(serper):
    """Concurrent duplicates must all get correct results and a consistent cache."""
    calls = serper()

    results = await asyncio.gather(*(_discover() for _ in range(8)))

    assert all(r == results[0] for r in results)
    assert len(get_search_cache()) == 1
    # Each coroutine checks the cache before any of them has awaited a result,
    # so duplicate in-flight calls are expected; correctness is what matters.
    assert calls["n"] <= 8


async def test_concurrent_distinct_requests_are_isolated(monkeypatch):
    async def fake(query, *, serper_api_key, k, timeout_s, client=None):
        await asyncio.sleep(0.01)
        return [{"link": f"https://{query}.example.com", "title": query, "snippet": "s"}]

    monkeypatch.setattr(search, "_serper_request", fake)

    queries = [f"query {i}" for i in range(5)]
    results = await asyncio.gather(*(_discover(q) for q in queries))

    for query, result in zip(queries, results):
        assert result[0]["url"] == f"https://{query}.example.com"


# -------------------------------------------------------------- disabling
async def test_cache_can_be_disabled(serper, monkeypatch):
    monkeypatch.setenv("AUTOSEARCH_SEARCH_CACHE_ENABLED", "false")
    from backend.services.cache import reset_search_cache

    reset_search_cache()
    calls = serper()

    await _discover()
    await _discover()
    assert calls["n"] == 2


async def test_use_cache_false_bypasses_cache(serper):
    calls = serper()
    await _discover()
    await _discover(use_cache=False)
    assert calls["n"] == 2


# ------------------------------------------------------ integration + keys
async def test_retrieval_reports_cache_hit_in_stats(serper, fake_fetch):
    from tests.conftest import RICH_TEXT, html_page

    serper()

    async def handler(url):
        return html_page(RICH_TEXT)

    fake_fetch(handler)

    first: dict = {}
    await search.retrieve_sources("repeat me", serper_api_key="k", stats=first)
    second: dict = {}
    await search.retrieve_sources("repeat me", serper_api_key="k", stats=second)

    assert first["search_cache_hit"] is False
    assert second["search_cache_hit"] is True
    assert second["status"] in {"ok", "partial"}


def test_cache_key_excludes_api_key_and_is_deterministic():
    """Keys must be stable and must never embed user credentials."""
    a = make_search_key("some query", k=6)
    b = make_search_key("some query", k=6)
    assert a == b
    assert len(a) == 64  # sha256 hex
    assert "some query" not in a


def test_cache_hit_rate_reporting():
    cache = TTLCache(max_entries=8, ttl_s=60)
    cache.set("k", "v")
    cache.get("k")
    cache.get("missing")
    stats = cache.stats()
    assert stats["hits"] == 1 and stats["misses"] == 1
    assert stats["hit_rate"] == 0.5
