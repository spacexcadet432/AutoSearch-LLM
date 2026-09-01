"""Reliability configuration.

Every externally-facing timeout, retry count and concurrency limit in the
request path is defined here so the policy can be read (and tuned) in one place
instead of being scattered as magic numbers.

All values are read from the environment at call time, so tests and the
evaluation harness can override them without reimporting the backend.
Defaults preserve the previously-shipped behaviour except where the old value
was unbounded, which is exactly what Phase 2 set out to fix.
"""

from __future__ import annotations

import os

# --- LLM ---------------------------------------------------------------
# The OpenAI SDK previously defaulted to a 600 s read timeout with 2 retries,
# so a single hung completion could occupy a request for ~30 minutes.
DEFAULT_LLM_TIMEOUT_S = 30.0
DEFAULT_LLM_CONNECT_TIMEOUT_S = 5.0
DEFAULT_LLM_MAX_RETRIES = 2

# --- Search provider (Serper) ------------------------------------------
DEFAULT_SEARCH_TIMEOUT_S = 6.0
DEFAULT_SEARCH_MAX_ATTEMPTS = 2          # 1 initial try + 1 retry
DEFAULT_SEARCH_RETRY_BASE_DELAY_S = 0.25

# --- Page fetching -----------------------------------------------------
DEFAULT_FETCH_TIMEOUT_S = 3.0
DEFAULT_FETCH_CONCURRENCY = 4
DEFAULT_MAX_DOWNLOAD_BYTES = 1_500_000

# --- Retrieval budget --------------------------------------------------
DEFAULT_RETRIEVAL_DEADLINE_MS = 3500

# --- Search result cache ----------------------------------------------
# Serper discovery was the dominant latency component in the Phase 1 baseline
# (~2.02 s mean), and search results for the same query are stable over short
# windows, so a short TTL is both safe and effective.
DEFAULT_SEARCH_CACHE_ENABLED = True
DEFAULT_SEARCH_CACHE_TTL_S = 300.0
DEFAULT_SEARCH_CACHE_MAX_ENTRIES = 256


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _int(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= minimum else default


def llm_timeout_s() -> float:
    return _float("AUTOSEARCH_LLM_TIMEOUT_S", DEFAULT_LLM_TIMEOUT_S)


def llm_connect_timeout_s() -> float:
    return _float("AUTOSEARCH_LLM_CONNECT_TIMEOUT_S", DEFAULT_LLM_CONNECT_TIMEOUT_S)


def llm_max_retries() -> int:
    """Retries for transient LLM failures, applied by the OpenAI SDK itself.

    The SDK retries connection errors, timeouts, 408/409/429 and 5xx with
    exponential backoff + jitter, and never retries 400/401/403/404. That is
    precisely the policy we want, so we configure it rather than reimplement it.
    """
    return _int("AUTOSEARCH_LLM_MAX_RETRIES", DEFAULT_LLM_MAX_RETRIES)


def search_timeout_s() -> float:
    return _float("AUTOSEARCH_SEARCH_TIMEOUT_S", DEFAULT_SEARCH_TIMEOUT_S)


def search_max_attempts() -> int:
    return max(1, _int("AUTOSEARCH_SEARCH_MAX_ATTEMPTS", DEFAULT_SEARCH_MAX_ATTEMPTS, minimum=1))


def search_retry_base_delay_s() -> float:
    return _float("AUTOSEARCH_SEARCH_RETRY_BASE_DELAY_S", DEFAULT_SEARCH_RETRY_BASE_DELAY_S)


def fetch_timeout_s() -> float:
    return _float("AUTOSEARCH_FETCH_TIMEOUT_S", DEFAULT_FETCH_TIMEOUT_S)


def fetch_concurrency() -> int:
    return max(1, _int("AUTOSEARCH_FETCH_CONCURRENCY", DEFAULT_FETCH_CONCURRENCY, minimum=1))


def max_download_bytes() -> int:
    return max(1024, _int("AUTOSEARCH_MAX_DOWNLOAD_BYTES", DEFAULT_MAX_DOWNLOAD_BYTES, minimum=1024))


def retrieval_deadline_ms() -> int:
    return max(
        250,
        _int("AUTOSEARCH_RETRIEVAL_DEADLINE_MS", DEFAULT_RETRIEVAL_DEADLINE_MS, minimum=250),
    )


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def search_cache_enabled() -> bool:
    return _bool("AUTOSEARCH_SEARCH_CACHE_ENABLED", DEFAULT_SEARCH_CACHE_ENABLED)


def search_cache_ttl_s() -> float:
    return _float("AUTOSEARCH_SEARCH_CACHE_TTL_S", DEFAULT_SEARCH_CACHE_TTL_S)


def search_cache_max_entries() -> int:
    return max(
        1,
        _int(
            "AUTOSEARCH_SEARCH_CACHE_MAX_ENTRIES",
            DEFAULT_SEARCH_CACHE_MAX_ENTRIES,
            minimum=1,
        ),
    )
