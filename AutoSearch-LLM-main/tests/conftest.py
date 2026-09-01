"""Shared test fixtures.

The whole suite is offline: no OpenAI/Bedrock/Serper calls, no API keys, no
network. External services are replaced with fakes so failure modes can be
triggered deterministically.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Every knob backend.services.config reads. Cleared before each test so a
# developer's real environment can never change a test outcome.
_CONFIG_ENV_VARS = [
    "AUTOSEARCH_LLM_BASE_URL",
    "AUTOSEARCH_LLM_MODEL",
    "AUTOSEARCH_LLM_TIMEOUT_S",
    "AUTOSEARCH_LLM_CONNECT_TIMEOUT_S",
    "AUTOSEARCH_LLM_MAX_RETRIES",
    "AUTOSEARCH_SEARCH_TIMEOUT_S",
    "AUTOSEARCH_SEARCH_MAX_ATTEMPTS",
    "AUTOSEARCH_SEARCH_RETRY_BASE_DELAY_S",
    "AUTOSEARCH_FETCH_TIMEOUT_S",
    "AUTOSEARCH_FETCH_CONCURRENCY",
    "AUTOSEARCH_MAX_DOWNLOAD_BYTES",
    "AUTOSEARCH_RETRIEVAL_DEADLINE_MS",
    "AUTOSEARCH_SEARCH_CACHE_ENABLED",
    "AUTOSEARCH_SEARCH_CACHE_TTL_S",
    "AUTOSEARCH_SEARCH_CACHE_MAX_ENTRIES",
]


@pytest.fixture(autouse=True)
def clean_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate tests from ambient configuration and credentials."""
    for name in _CONFIG_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    for name in ("OPENAI_API_KEY", "SERPER_API_KEY", "AWS_BEARER_TOKEN_BEDROCK"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def reset_cache() -> None:
    """Give every test a fresh cache built from that test's configuration."""
    from backend.services.cache import reset_search_cache

    reset_search_cache()
    yield
    reset_search_cache()


def make_candidates(n: int, *, snippet: str | None = None) -> list[dict[str, Any]]:
    """Build n fake Serper results."""
    text = snippet if snippet is not None else "a useful snippet " * 5
    return [
        {
            "url": f"https://site{i}.example.com/article-{i}",
            "title": f"Title {i}",
            "snippet": text,
        }
        for i in range(n)
    ]


def html_page(body: str) -> str:
    """A page whose extracted text is comfortably above the thin-content cut-off."""
    return f"<html><body><article><p>{body}</p></article></body></html>"


RICH_TEXT = (
    "This paragraph exists to comfortably exceed the two hundred and twenty "
    "character minimum that the retrieval pipeline requires before it treats "
    "extracted page text as usable content rather than falling back to the "
    "search engine snippet for the very same URL. It repeats itself a little."
)


@pytest.fixture
def fake_discover(monkeypatch: pytest.MonkeyPatch):
    """Replace Serper discovery with a controllable fake."""
    import backend.services.search as search

    def _install(candidates: list[dict[str, Any]] | Exception):
        async def _discover(query: str, *, serper_api_key: str, k: int = 8, **kwargs):
            if isinstance(candidates, Exception):
                raise candidates
            return candidates

        monkeypatch.setattr(search, "discover_urls", _discover)

    return _install


@pytest.fixture
def fake_fetch(monkeypatch: pytest.MonkeyPatch):
    """Replace page fetching with a per-URL controllable fake."""
    import backend.services.search as search

    def _install(handler):
        async def _fetch(url, *, client, timeout_s=3.0, max_bytes=1_500_000):
            return await handler(url)

        monkeypatch.setattr(search, "fetch_html", _fetch)

    return _install
