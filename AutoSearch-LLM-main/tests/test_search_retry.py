"""Serper retry policy: retry transient failures only, with a bounded budget."""

from __future__ import annotations

import httpx
import pytest

import backend.services.search as search
from backend.services.errors import SearchProviderError


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    """Keep backoff out of the test runtime without disabling it."""
    monkeypatch.setenv("AUTOSEARCH_SEARCH_RETRY_BASE_DELAY_S", "0.001")


def _install_serper(monkeypatch, responses):
    """Queue a sequence of per-attempt outcomes; returns the attempt counter."""
    calls = {"n": 0}

    async def fake_request(query, *, serper_api_key, k, timeout_s, client=None):
        index = calls["n"]
        calls["n"] += 1
        outcome = responses[min(index, len(responses) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(search, "_serper_request", fake_request)
    return calls


ORGANIC = [{"link": "https://a.example.com", "title": "t", "snippet": "s"}]


async def test_transient_failure_is_retried_and_can_succeed(monkeypatch):
    calls = _install_serper(
        monkeypatch,
        [SearchProviderError("timeout", retryable=True), ORGANIC],
    )
    results = await search.discover_urls("q", serper_api_key="k")
    assert calls["n"] == 2
    assert results[0]["url"] == "https://a.example.com"


async def test_auth_failure_is_not_retried(monkeypatch):
    """A bad key will never succeed: retrying only burns quota."""
    calls = _install_serper(
        monkeypatch,
        [SearchProviderError("bad key", retryable=False, status_code=401)],
    )
    with pytest.raises(SearchProviderError):
        await search.discover_urls("q", serper_api_key="k")
    assert calls["n"] == 1


async def test_retry_budget_is_bounded(monkeypatch):
    """Persistent transient failure stops at max_attempts - no retry storm."""
    monkeypatch.setenv("AUTOSEARCH_SEARCH_MAX_ATTEMPTS", "3")
    calls = _install_serper(
        monkeypatch, [SearchProviderError("boom", retryable=True)]
    )
    with pytest.raises(SearchProviderError):
        await search.discover_urls("q", serper_api_key="k")
    assert calls["n"] == 3


async def test_retry_count_is_configurable(monkeypatch):
    monkeypatch.setenv("AUTOSEARCH_SEARCH_MAX_ATTEMPTS", "1")
    calls = _install_serper(
        monkeypatch, [SearchProviderError("boom", retryable=True)]
    )
    with pytest.raises(SearchProviderError):
        await search.discover_urls("q", serper_api_key="k")
    assert calls["n"] == 1, "max_attempts=1 must mean no retry"


# ---------------------------------------------- status-code classification
@pytest.mark.parametrize("status,retryable", [
    (429, True), (500, True), (502, True), (503, True), (504, True),
    (400, False), (401, False), (403, False), (404, False),
])
async def test_status_code_retryability(monkeypatch, status, retryable):
    """Rate limits and server errors are transient; client errors are not."""
    def handler(request):
        return httpx.Response(status, json={})

    monkeypatch.setattr(
        httpx.AsyncClient, "post",
        lambda self, url, **kw: _respond(handler, url),
    )

    with pytest.raises(SearchProviderError) as excinfo:
        await search._serper_request("q", serper_api_key="k", k=3, timeout_s=1.0)
    assert excinfo.value.retryable is retryable
    assert excinfo.value.status_code == status


async def _respond(handler, url):
    return handler(httpx.Request("POST", url))


async def test_timeout_is_classified_retryable(monkeypatch):
    async def raise_timeout(self, url, **kwargs):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx.AsyncClient, "post", raise_timeout)
    with pytest.raises(SearchProviderError) as excinfo:
        await search._serper_request("q", serper_api_key="k", k=3, timeout_s=1.0)
    assert excinfo.value.retryable is True


async def test_malformed_json_body_is_retryable(monkeypatch):
    async def bad_json(self, url, **kwargs):
        return httpx.Response(200, content=b"not json at all")

    monkeypatch.setattr(httpx.AsyncClient, "post", bad_json)
    with pytest.raises(SearchProviderError) as excinfo:
        await search._serper_request("q", serper_api_key="k", k=3, timeout_s=1.0)
    assert excinfo.value.retryable is True
