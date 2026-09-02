"""API boundary: predictable status codes, no leaked internals."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

import backend.routes.query as query_route
from backend.main import app
from backend.services.errors import SearchProviderError

client = TestClient(app, raise_server_exceptions=False)

BODY = {"query": "a question", "openai_api_key": "sk-test", "serper_api_key": "serper-test"}


def _openai_error(cls, status):
    """Build a real SDK exception instance without touching the network."""
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status, request=request, json={"error": {"message": "x"}})
    return cls("boom", response=response, body=None)


@pytest.fixture
def failing_pipeline(monkeypatch):
    def _install(error):
        async def boom(*args, **kwargs):
            raise error
        monkeypatch.setattr(query_route, "run_query_pipeline", boom)
    return _install


def test_health_endpoint():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "uptime_s" in body and "cache" in body


def test_missing_keys_returns_400():
    r = client.post("/query", json={"query": "hello"})
    assert r.status_code == 400
    assert "missing credentials" in r.json()["detail"].lower()


def test_successful_response_shape(monkeypatch):
    async def ok(*args, **kwargs):
        return {
            "answer": "hi", "used_search": True, "sources": ["https://a.example.com"],
            "latency": 1.0, "routing_decision": "search", "confidence": 0.9,
            "retrieval_status": "partial", "grounded": True,
        }

    monkeypatch.setattr(query_route, "run_query_pipeline", ok)
    r = client.post("/query", json=BODY)
    assert r.status_code == 200
    payload = r.json()
    assert payload["grounded"] is True
    assert payload["retrieval_status"] == "partial"
    # Original contract fields must still be present for existing clients.
    for key in ("answer", "used_search", "sources", "latency", "routing_decision"):
        assert key in payload


@pytest.mark.parametrize("error,expected_status", [
    (_openai_error(AuthenticationError, 401), 401),
    (_openai_error(RateLimitError, 429), 429),
    (APITimeoutError(httpx.Request("POST", "https://api.openai.com/v1/x")), 504),
    (APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/x")), 502),
    (SearchProviderError("serper down", retryable=True), 503),
    (ValueError("some internal bug"), 500),
])
def test_errors_map_to_specific_status_codes(failing_pipeline, error, expected_status):
    failing_pipeline(error)
    r = client.post("/query", json=BODY)
    assert r.status_code == expected_status


@pytest.mark.parametrize("error", [
    _openai_error(AuthenticationError, 401),
    APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/x")),
    ValueError("Traceback secret: sk-live-abcdef123456"),
    SearchProviderError("serper key sk-serper-9999 rejected", retryable=False),
])
def test_error_responses_never_leak_internals(failing_pipeline, error):
    """No API keys, no stack traces, no raw provider text in the response body."""
    failing_pipeline(error)
    r = client.post("/query", json=BODY)
    body = r.text.lower()

    assert "traceback" not in body
    assert "sk-live" not in body
    assert "sk-serper" not in body
    assert "sk-test" not in body
    assert "serper-test" not in body
    # The detail must be one of our fixed, safe messages.
    assert len(r.json()["detail"]) < 200


def test_unexpected_error_is_logged_with_traceback(failing_pipeline, caplog):
    """Programming errors must remain diagnosable server-side."""
    failing_pipeline(ValueError("a real bug"))
    with caplog.at_level("ERROR"):
        r = client.post("/query", json=BODY)

    assert r.status_code == 500
    assert any(rec.exc_info for rec in caplog.records), "expected a logged traceback"


def test_short_query_is_rejected_by_validation():
    r = client.post("/query", json={**BODY, "query": "a"})
    assert r.status_code == 422
