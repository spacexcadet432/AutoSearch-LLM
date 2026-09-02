"""Production hardening: credentials, CORS, docs exposure, health, logging safety."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

import backend.main
from backend.services import config
from backend.services.credentials import (
    resolve_llm_key,
    resolve_search_key,
    server_credentials_present,
)


def _reload_app(monkeypatch, **env):
    """Rebuild the app so import-time settings (CORS, docs) are re-read."""
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(backend.main)


@pytest.fixture(autouse=True)
def _restore_app():
    yield
    importlib.reload(backend.main)


# ------------------------------------------------------------ credentials
def test_request_key_takes_precedence(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "server-token")
    assert resolve_llm_key("request-key") == "request-key"


def test_falls_back_to_server_bedrock_token(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "server-token")
    assert resolve_llm_key(None) == "server-token"
    assert resolve_llm_key("") == "server-token"


def test_falls_back_to_openai_key_when_no_bedrock(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-server")
    assert resolve_llm_key(None) == "sk-server"


def test_no_credentials_resolves_empty():
    assert resolve_llm_key(None) == ""
    assert resolve_search_key(None) == ""


def test_credential_presence_reports_booleans_only(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "super-secret-token")
    monkeypatch.setenv("SERPER_API_KEY", "serper-secret")
    present = server_credentials_present()
    assert present == {"llm": True, "search": True}
    assert "super-secret-token" not in str(present)


def test_query_works_without_request_keys_when_server_configured(monkeypatch):
    """The EC2 deployment model: caller sends no keys."""
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "server-token")
    monkeypatch.setenv("SERPER_API_KEY", "serper-token")

    import backend.routes.query as route

    async def fake_pipeline(query, *, openai_api_key, serper_api_key, trace=None):
        assert openai_api_key == "server-token"
        assert serper_api_key == "serper-token"
        return {
            "answer": "ok", "used_search": False, "sources": [], "latency": 0.1,
            "routing_decision": "direct", "confidence": 0.5,
            "retrieval_status": None, "grounded": False,
        }

    monkeypatch.setattr(route, "run_query_pipeline", fake_pipeline)
    with TestClient(backend.main.app) as client:
        r = client.post("/query", json={"query": "a question"})
    assert r.status_code == 200


def test_query_still_rejects_when_no_credentials_anywhere():
    with TestClient(backend.main.app) as client:
        r = client.post("/query", json={"query": "a question"})
    assert r.status_code == 400
    assert "Missing credentials" in r.json()["detail"]


# -------------------------------------------------------------- endpoints
def test_health_reports_state_without_calling_external_apis(monkeypatch):
    monkeypatch.setenv("SERPER_API_KEY", "serper-secret-value")
    with TestClient(backend.main.app) as client:
        body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["credentials_configured"]["search"] is True
    assert "cache" in body and "hits" in body["cache"]
    # No secret may appear anywhere in the payload.
    assert "serper-secret-value" not in str(body)


def test_docs_enabled_by_default_in_development():
    assert config.enable_docs() is True
    with TestClient(backend.main.app) as client:
        assert client.get("/docs").status_code == 200


def test_docs_disabled_in_production(monkeypatch):
    module = _reload_app(monkeypatch, AUTOSEARCH_ENV="production")
    with TestClient(module.app) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404
        # The service itself still works.
        assert client.get("/health").status_code == 200


def test_docs_can_be_force_enabled_in_production(monkeypatch):
    monkeypatch.setenv("AUTOSEARCH_ENV", "production")
    monkeypatch.setenv("AUTOSEARCH_ENABLE_DOCS", "true")
    assert config.enable_docs() is True


# ------------------------------------------------------------------ CORS
def test_wildcard_origin_does_not_allow_credentials(monkeypatch):
    """Wildcard + credentials is rejected by browsers and is unsafe."""
    module = _reload_app(monkeypatch, AUTOSEARCH_ALLOWED_ORIGINS="*")
    with TestClient(module.app) as client:
        r = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert r.headers.get("access-control-allow-origin") == "*"
    assert r.headers.get("access-control-allow-credentials") is None


def test_explicit_origins_are_restricted(monkeypatch):
    module = _reload_app(
        monkeypatch, AUTOSEARCH_ALLOWED_ORIGINS="https://good.example.com"
    )
    with TestClient(module.app) as client:
        allowed = client.get("/health", headers={"Origin": "https://good.example.com"})
        denied = client.get("/health", headers={"Origin": "https://evil.example.com"})

    assert allowed.headers.get("access-control-allow-origin") == "https://good.example.com"
    assert denied.headers.get("access-control-allow-origin") != "https://evil.example.com"


def test_allowed_origins_parses_a_list(monkeypatch):
    monkeypatch.setenv("AUTOSEARCH_ALLOWED_ORIGINS", "https://a.com, https://b.com")
    assert config.allowed_origins() == ["https://a.com", "https://b.com"]


# --------------------------------------------------------------- config
def test_public_config_summary_contains_no_secrets(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "top-secret-token")
    monkeypatch.setenv("SERPER_API_KEY", "another-secret")
    summary = str(config.public_config_summary())
    assert "top-secret-token" not in summary
    assert "another-secret" not in summary


def test_production_defaults(monkeypatch):
    monkeypatch.setenv("AUTOSEARCH_ENV", "production")
    assert config.is_production() is True
    assert config.enable_docs() is False


def test_bind_defaults():
    assert config.bind_port() == 8000
    assert config.bind_host() == "0.0.0.0"


def test_request_logging_excludes_secrets(monkeypatch, caplog):
    """The access log must never contain a supplied API key."""
    import backend.routes.query as route

    async def fake_pipeline(query, *, openai_api_key, serper_api_key, trace=None):
        return {
            "answer": "ok", "used_search": False, "sources": [], "latency": 0.1,
            "routing_decision": "direct", "confidence": 0.5,
            "retrieval_status": None, "grounded": False,
        }

    monkeypatch.setattr(route, "run_query_pipeline", fake_pipeline)
    with caplog.at_level("INFO"):
        with TestClient(backend.main.app) as client:
            client.post(
                "/query",
                json={"query": "hello there"},
                headers={
                    "X-OpenAI-API-Key": "sk-should-never-be-logged",
                    "X-Serper-API-Key": "serper-should-never-be-logged",
                },
            )

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "should-never-be-logged" not in logged
    assert "/query" in logged  # the request itself is logged
