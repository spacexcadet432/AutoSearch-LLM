"""End-to-end wiring test.

Exercises the real pipeline, real retrieval, real chunking and real ranking.
Only the two network boundaries (Serper, page fetch) and the LLM are faked,
so this catches integration breakage that per-module tests would miss.
"""

from __future__ import annotations

import httpx
import pytest

import backend.services.pipeline as pipeline
import backend.services.search as search
from tests.conftest import RICH_TEXT, html_page, make_candidates


@pytest.fixture
def wired(monkeypatch):
    """Fake only the external boundaries; everything else runs for real."""
    seen: dict = {"grounded_sources": None}

    def _install(*, fetch_handler, needs_search=True, candidates=None):
        async def discover(query, *, serper_api_key, k=8, **kwargs):
            return candidates if candidates is not None else make_candidates(3)

        async def fetch(url, *, client, timeout_s=3.0, max_bytes=1_500_000):
            return await fetch_handler(url)

        async def classify(query, api_key):
            return needs_search, 0.88

        async def grounded(query, sources, api_key):
            seen["grounded_sources"] = sources
            return "Grounded answer built from the retrieved sources."

        async def standard(query, api_key):
            return "Direct answer from model knowledge."

        monkeypatch.setattr(search, "discover_urls", discover)
        monkeypatch.setattr(search, "fetch_html", fetch)
        monkeypatch.setattr(pipeline, "classify_temporal_need", classify)
        monkeypatch.setattr(pipeline, "generate_grounded_answer", grounded)
        monkeypatch.setattr(pipeline, "generate_standard_answer", standard)
        return seen

    return _install


async def _run():
    trace: dict = {}
    result = await pipeline.run_query_pipeline(
        "what is the current price of something",
        openai_api_key="k",
        serper_api_key="s",
        trace=trace,
    )
    return result, trace


async def test_full_success_path(wired):
    async def handler(url):
        return html_page(RICH_TEXT)

    seen = wired(fetch_handler=handler)
    result, trace = await _run()

    assert result["grounded"] is True
    assert result["retrieval_status"] == "ok"
    assert result["sources"], "expected real ranked source URLs"
    assert result["answer"].startswith("Grounded answer")
    # Chunks really flowed through extraction -> chunking -> ranking.
    assert seen["grounded_sources"]
    assert all("chunk_text" in s for s in seen["grounded_sources"])
    assert trace["retrieval"]["status"] == "ok"


async def test_partial_failure_still_answers_with_surviving_sources(wired):
    candidates = make_candidates(3)
    dead = candidates[0]["url"]

    async def handler(url):
        if url == dead:
            raise httpx.ConnectError("refused")
        return html_page(RICH_TEXT)

    wired(fetch_handler=handler, candidates=candidates)
    result, trace = await _run()

    assert result["grounded"] is True
    assert result["retrieval_status"] == "partial"
    assert dead not in result["sources"]
    assert result["sources"]


async def test_total_fetch_failure_degrades_to_snippets_end_to_end(wired):
    async def handler(url):
        raise httpx.ConnectError("all dead")

    wired(fetch_handler=handler)
    result, trace = await _run()

    # Still answers, still cites real URLs, and says the retrieval was degraded.
    assert result["sources"]
    assert result["retrieval_status"] == "partial"
    assert trace["retrieval"]["degraded_to_snippets"] is True


async def test_search_provider_down_falls_back_to_direct(wired, monkeypatch):
    from backend.services.errors import SearchProviderError

    async def dead_discover(query, *, serper_api_key, k=8, **kwargs):
        raise SearchProviderError("provider down", retryable=True)

    async def handler(url):  # never reached
        return html_page(RICH_TEXT)

    wired(fetch_handler=handler)
    monkeypatch.setattr(search, "discover_urls", dead_discover)

    result, _ = await _run()

    assert result["answer"].startswith("Direct answer")
    assert result["grounded"] is False
    assert result["sources"] == []
    assert result["retrieval_status"] == "failed"


async def test_direct_route_end_to_end(wired):
    async def handler(url):  # never reached
        raise AssertionError("retrieval must not run on the direct route")

    wired(fetch_handler=handler, needs_search=False)
    result, trace = await _run()

    assert result["routing_decision"] == "direct"
    assert result["grounded"] is False
    assert trace["generation_mode"] == "direct"
