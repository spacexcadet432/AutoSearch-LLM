"""Timeout and retry configuration: nothing external may wait forever."""

from __future__ import annotations

import pytest

from backend.services import config
from backend.services.llm import build_client, chat_model, provider_label


# ------------------------------------------------------------- LLM bounds
def test_llm_client_has_a_bounded_timeout():
    """Regression guard: the SDK default is 600s, which is not acceptable."""
    client = build_client("test-key")
    assert client.timeout.read is not None
    assert client.timeout.read <= 60, "LLM read timeout must be bounded and short"
    assert client.timeout.connect is not None
    assert client.timeout.connect <= 15


def test_llm_retries_are_bounded():
    client = build_client("test-key")
    assert 0 <= client.max_retries <= 5


def test_llm_timeout_is_configurable(monkeypatch):
    monkeypatch.setenv("AUTOSEARCH_LLM_TIMEOUT_S", "7")
    monkeypatch.setenv("AUTOSEARCH_LLM_MAX_RETRIES", "0")
    client = build_client("test-key")
    assert client.timeout.read == 7
    assert client.max_retries == 0


def test_explicit_arguments_override_environment(monkeypatch):
    monkeypatch.setenv("AUTOSEARCH_LLM_TIMEOUT_S", "7")
    client = build_client("test-key", timeout_s=3, max_retries=1)
    assert client.timeout.read == 3
    assert client.max_retries == 1


def test_defaults_preserve_openai_provider():
    """With no env set, behaviour matches the originally shipped configuration."""
    assert chat_model() == "gpt-4o-mini"
    assert "api.openai.com" in provider_label()


def test_base_url_is_configurable(monkeypatch):
    monkeypatch.setenv("AUTOSEARCH_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AUTOSEARCH_LLM_MODEL", "some-model")
    assert "example.test" in provider_label()
    assert chat_model() == "some-model"


# ---------------------------------------------------------- config parsing
def test_every_external_operation_has_a_bounded_default():
    """No external call may be unbounded."""
    assert 0 < config.llm_timeout_s() < 120
    assert 0 < config.search_timeout_s() < 60
    assert 0 < config.fetch_timeout_s() < 60
    assert 0 < config.retrieval_deadline_ms() < 60_000
    assert config.fetch_concurrency() >= 1
    assert config.search_max_attempts() >= 1


@pytest.mark.parametrize("value", ["", "   ", "not-a-number", "-5", "0"])
def test_invalid_config_values_fall_back_to_safe_defaults(monkeypatch, value):
    """A malformed env var must never disable a timeout."""
    monkeypatch.setenv("AUTOSEARCH_LLM_TIMEOUT_S", value)
    monkeypatch.setenv("AUTOSEARCH_FETCH_TIMEOUT_S", value)
    assert config.llm_timeout_s() == config.DEFAULT_LLM_TIMEOUT_S
    assert config.fetch_timeout_s() == config.DEFAULT_FETCH_TIMEOUT_S


@pytest.mark.parametrize("value", ["not-a-number", "-3"])
def test_invalid_int_config_falls_back(monkeypatch, value):
    monkeypatch.setenv("AUTOSEARCH_FETCH_CONCURRENCY", value)
    monkeypatch.setenv("AUTOSEARCH_SEARCH_MAX_ATTEMPTS", value)
    assert config.fetch_concurrency() == config.DEFAULT_FETCH_CONCURRENCY
    assert config.search_max_attempts() == config.DEFAULT_SEARCH_MAX_ATTEMPTS


def test_config_values_are_read_at_call_time(monkeypatch):
    """Lets tests and the eval harness reconfigure without reimporting."""
    before = config.fetch_concurrency()
    monkeypatch.setenv("AUTOSEARCH_FETCH_CONCURRENCY", str(before + 3))
    assert config.fetch_concurrency() == before + 3


def test_no_api_keys_required_to_import_backend():
    """The suite must run with no credentials present."""
    import os

    for name in ("OPENAI_API_KEY", "SERPER_API_KEY", "AWS_BEARER_TOKEN_BEDROCK"):
        assert not os.getenv(name), f"{name} leaked into the test environment"

    from backend.main import app

    assert "/query" in app.openapi()["paths"]
