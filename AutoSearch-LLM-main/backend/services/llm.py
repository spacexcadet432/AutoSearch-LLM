"""LLM provider configuration.

Isolates *where* chat completions are sent so the same pipeline can run against
any OpenAI-compatible endpoint (OpenAI, xAI/Grok, Groq, ...) without changing
routing, retrieval or generation logic.

Defaults preserve the original behaviour exactly: when no environment variables
are set, this resolves to the OpenAI API with ``gpt-4o-mini``.

Environment variables (all optional):
    AUTOSEARCH_LLM_BASE_URL   OpenAI-compatible base URL, e.g. https://api.x.ai/v1
    AUTOSEARCH_LLM_MODEL      Chat model id
    AUTOSEARCH_LLM_TIMEOUT_S  Per-request read timeout (see backend.services.config)
    AUTOSEARCH_LLM_MAX_RETRIES  Bounded retries for transient failures

Values are read at call time (not import time) so a harness can configure the
provider after importing the backend.
"""

from __future__ import annotations

import os

import httpx
from openai import AsyncOpenAI

from backend.services import config

DEFAULT_MODEL = "gpt-4o-mini"


def chat_model() -> str:
    """Return the chat model id to use for routing and generation."""
    return os.getenv("AUTOSEARCH_LLM_MODEL") or DEFAULT_MODEL


def base_url() -> str | None:
    """Return the OpenAI-compatible base URL, or None for the OpenAI default."""
    return os.getenv("AUTOSEARCH_LLM_BASE_URL") or None


def build_client(
    api_key: str,
    *,
    timeout_s: float | None = None,
    max_retries: int | None = None,
) -> AsyncOpenAI:
    """Build a request-scoped chat client with a BOUNDED timeout.

    The SDK default is a 600 s read timeout with 2 retries, so a single stalled
    completion could hold a request open for roughly half an hour. Every client
    built here carries an explicit, short timeout instead.

    Retries are delegated to the SDK, which already retries only transient
    failures (connection errors, timeouts, 408/409/429, 5xx) with exponential
    backoff and jitter, and never retries 400/401/403/404.
    """
    timeout = httpx.Timeout(
        timeout_s if timeout_s is not None else config.llm_timeout_s(),
        connect=config.llm_connect_timeout_s(),
    )
    retries = max_retries if max_retries is not None else config.llm_max_retries()
    kwargs = {"api_key": api_key, "timeout": timeout, "max_retries": retries}
    url = base_url()
    if url:
        kwargs["base_url"] = url
    return AsyncOpenAI(**kwargs)


def provider_label() -> str:
    """Human-readable provider description for evaluation metadata (no secrets)."""
    return f"{base_url() or 'https://api.openai.com/v1'} :: {chat_model()}"
