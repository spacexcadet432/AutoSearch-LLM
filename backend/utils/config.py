"""Configuration helpers for backend services."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def get_serper_api_key() -> str:
    """Return Serper API key from environment or raise a clear error."""
    api_key = os.getenv("SERPER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SERPER_API_KEY is missing from environment.")
    return api_key


def resolve_openai_api_key(request_key: str | None) -> str:
    """
    Resolve OpenAI API key for one request.

    Priority:
    1) key supplied by client in request
    2) fallback to OPENAI_API_KEY from environment
    """
    if request_key and request_key.strip():
        return request_key.strip()

    env_key = os.getenv("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key

    raise RuntimeError("OpenAI API key missing. Provide `api_key` in request.")
