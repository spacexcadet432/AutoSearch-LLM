"""Credential resolution.

Supports both deployment models without changing the API contract:

* **BYO keys** (original behaviour) - the caller supplies keys per request.
* **Environment keys** - credentials come from .env / the environment and the
  caller supplies none. This is how the CLI runs.

Request-supplied keys always win, so an existing BYO client is unaffected.
Keys are only ever read, never logged or returned.
"""

from __future__ import annotations

import os

# Checked in order. The Bedrock bearer token comes first because Bedrock is
# the default configured provider.
_LLM_KEY_ENVS = ("AWS_BEARER_TOKEN_BEDROCK", "OPENAI_API_KEY")
_SEARCH_KEY_ENVS = ("SERPER_API_KEY",)


def _from_env(names: tuple[str, ...]) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value:
            return value
    return ""


def resolve_llm_key(request_key: str | None = None) -> str:
    """Request-supplied LLM key, else the server's configured key."""
    return (request_key or "").strip() or _from_env(_LLM_KEY_ENVS)


def resolve_search_key(request_key: str | None = None) -> str:
    """Request-supplied Serper key, else the server's configured key."""
    return (request_key or "").strip() or _from_env(_SEARCH_KEY_ENVS)


def server_credentials_present() -> dict[str, bool]:
    """Which credentials the server itself holds. Booleans only - never values."""
    return {
        "llm": bool(_from_env(_LLM_KEY_ENVS)),
        "search": bool(_from_env(_SEARCH_KEY_ENVS)),
    }
