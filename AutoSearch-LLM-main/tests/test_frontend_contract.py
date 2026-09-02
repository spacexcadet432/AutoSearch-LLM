"""Frontend/backend contract.

Pins the exact JSON shape the frontend reads in frontend/src/routes/index.tsx.
If the backend stops emitting one of these fields, the UI silently degrades, so
these assertions are the integration guard.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.main
import backend.routes.query as route

FRONTEND_ORIGIN = "https://frontend.example.com"


def _ok_payload():
    return {
        "answer": "An answer.",
        "used_search": True,
        "sources": ["https://a.example.com", "https://b.example.com"],
        "latency": 1.234,
        "routing_decision": "search",
        "confidence": 0.91,
        "retrieval_status": "partial",
        "grounded": True,
    }


@pytest.fixture
def stub_pipeline(monkeypatch):
    def _install(payload=None, error=None, capture=None):
        async def fake(query, *, openai_api_key, serper_api_key, trace=None):
            if capture is not None:
                capture["llm"] = openai_api_key
                capture["search"] = serper_api_key
            if error:
                raise error
            return payload or _ok_payload()

        monkeypatch.setattr(route, "run_query_pipeline", fake)

    return _install


# --------------------------------------------------------- /health contract
def test_health_exposes_credentials_configured_for_the_ui(monkeypatch):
    """The UI reads credentials_configured.llm/.search to decide if keys are needed."""
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "server-llm")
    monkeypatch.setenv("SERPER_API_KEY", "server-search")

    with TestClient(backend.main.app) as client:
        body = client.get("/health").json()

    assert body["status"] == "ok"
    creds = body["credentials_configured"]
    assert creds["llm"] is True and creds["search"] is True
    assert "server-llm" not in str(body) and "server-search" not in str(body)


def test_health_reports_false_when_server_has_no_keys():
    with TestClient(backend.main.app) as client:
        creds = client.get("/health").json()["credentials_configured"]
    assert creds == {"llm": False, "search": False}


# ---------------------------------------------------------- /query contract
def test_query_response_contains_every_field_the_ui_reads(stub_pipeline):
    stub_pipeline()
    with TestClient(backend.main.app) as client:
        r = client.post(
            "/query",
            json={"query": "a question", "openai_api_key": "k", "serper_api_key": "s"},
        )

    assert r.status_code == 200
    body = r.json()
    for field in (
        "answer", "used_search", "sources", "latency",
        "routing_decision", "confidence", "retrieval_status", "grounded",
    ):
        assert field in body, f"UI reads '{field}' but the backend did not return it"

    assert isinstance(body["sources"], list)
    assert isinstance(body["latency"], (int, float))   # UI multiplies by 1000
    assert isinstance(body["grounded"], bool)


@pytest.mark.parametrize(
    "status",
    ["ok", "partial", "no_results", "no_useful_results", "failed", None],
)
def test_all_retrieval_status_values_the_ui_maps(stub_pipeline, status):
    """Every value the UI's retrievalNote() switch handles must be reachable."""
    payload = _ok_payload() | {"retrieval_status": status}
    stub_pipeline(payload)
    with TestClient(backend.main.app) as client:
        r = client.post("/query", json={"query": "a question",
                                        "openai_api_key": "k", "serper_api_key": "s"})
    assert r.json()["retrieval_status"] == status


def test_ui_can_omit_keys_when_server_has_them(monkeypatch, stub_pipeline):
    """The UI sends no key fields when the user supplied none."""
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "server-llm")
    monkeypatch.setenv("SERPER_API_KEY", "server-search")
    captured: dict = {}
    stub_pipeline(capture=captured)

    with TestClient(backend.main.app) as client:
        r = client.post("/query", json={"query": "a question"})

    assert r.status_code == 200
    assert captured == {"llm": "server-llm", "search": "server-search"}


def test_user_supplied_keys_override_server_keys(monkeypatch, stub_pipeline):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "server-llm")
    monkeypatch.setenv("SERPER_API_KEY", "server-search")
    captured: dict = {}
    stub_pipeline(capture=captured)

    with TestClient(backend.main.app) as client:
        client.post(
            "/query",
            json={"query": "a question", "openai_api_key": "user-llm",
                  "serper_api_key": "user-search"},
        )

    assert captured == {"llm": "user-llm", "search": "user-search"}


def test_errors_return_a_string_detail_the_ui_can_display(stub_pipeline):
    """The UI reads payload.detail as a string on non-2xx."""
    stub_pipeline(error=ValueError("internal"))
    with TestClient(backend.main.app) as client:
        r = client.post("/query", json={"query": "a question",
                                        "openai_api_key": "k", "serper_api_key": "s"})

    assert r.status_code == 500
    assert isinstance(r.json()["detail"], str)


# ------------------------------------------------------------------- CORS
def test_browser_origin_is_allowed_when_configured(monkeypatch):
    """Without this the browser blocks the response and fetch() rejects."""
    import importlib

    monkeypatch.setenv("AUTOSEARCH_ALLOWED_ORIGINS", FRONTEND_ORIGIN)
    module = importlib.reload(backend.main)
    try:
        with TestClient(module.app) as client:
            preflight = client.options(
                "/query",
                headers={
                    "Origin": FRONTEND_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
            health = client.get("/health", headers={"Origin": FRONTEND_ORIGIN})

        assert preflight.status_code in (200, 204)
        assert preflight.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
        assert health.headers["access-control-allow-origin"] == FRONTEND_ORIGIN
    finally:
        importlib.reload(backend.main)
