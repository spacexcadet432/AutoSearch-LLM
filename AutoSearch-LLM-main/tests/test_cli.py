"""CLI tests. Fully offline - the pipeline is stubbed, no external calls."""

from __future__ import annotations

import pytest

from autosearch import cli


@pytest.fixture
def configured(monkeypatch):
    """Minimum valid configuration (fake values, never used for real calls)."""
    monkeypatch.setenv("SERPER_API_KEY", "test-search-key")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "test-llm-key")
    monkeypatch.setenv("AUTOSEARCH_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("AUTOSEARCH_LLM_MODEL", "test-model")
    # main() calls load_dotenv(); stop it reading the developer's real .env.
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: False)


@pytest.fixture
def stub_pipeline(monkeypatch):
    calls: list[str] = []

    def _install(result=None, error=None):
        async def fake(query, *, openai_api_key, serper_api_key, trace=None):
            calls.append(query)
            if error:
                raise error
            return result or RESULT_GROUNDED

        monkeypatch.setattr(cli, "run_query_pipeline", fake)
        return calls

    return _install


RESULT_GROUNDED = {
    "answer": "The grounded answer.",
    "used_search": True,
    "sources": ["https://a.example.com", "https://b.example.com"],
    "latency": 2.5,
    "routing_decision": "search",
    "confidence": 0.92,
    "retrieval_status": "ok",
    "grounded": True,
}

RESULT_DIRECT = {
    "answer": "A direct answer.",
    "used_search": False,
    "sources": [],
    "latency": 0.8,
    "routing_decision": "direct",
    "confidence": 0.95,
    "retrieval_status": None,
    "grounded": False,
}


# ------------------------------------------------------ config validation
def test_missing_search_key_is_reported(monkeypatch, capsys):
    monkeypatch.delenv("SERPER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: False)

    assert cli.main(["--check"]) == 2
    err = capsys.readouterr().err
    assert "SERPER_API_KEY" in err
    assert "Traceback" not in err


def test_missing_llm_key_is_reported(monkeypatch, capsys):
    monkeypatch.setenv("SERPER_API_KEY", "k")
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: False)

    assert cli.main(["--check"]) == 2
    err = capsys.readouterr().err
    assert "AWS_BEARER_TOKEN_BEDROCK" in err and "OPENAI_API_KEY" in err


def test_bedrock_token_without_base_url_is_caught(monkeypatch, capsys):
    """Otherwise the token goes to OpenAI and fails with a confusing 401."""
    monkeypatch.setenv("SERPER_API_KEY", "k")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "t")
    monkeypatch.delenv("AUTOSEARCH_LLM_BASE_URL", raising=False)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: False)

    assert cli.main(["--check"]) == 2
    assert "AUTOSEARCH_LLM_BASE_URL" in capsys.readouterr().err


def test_check_passes_with_valid_config(configured, capsys):
    assert cli.main(["--check"]) == 0
    assert "Configuration OK" in capsys.readouterr().out


def test_check_makes_no_api_call(configured, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("--check must not call the pipeline")

    monkeypatch.setattr(cli, "run_query_pipeline", explode)
    assert cli.main(["--check"]) == 0


# ------------------------------------------------------- query execution
def test_single_query_runs_and_renders(configured, stub_pipeline, capsys):
    calls = stub_pipeline()
    assert cli.main(["What", "is", "the", "latest", "news?"]) == 0

    out = capsys.readouterr().out
    assert calls == ["What is the latest news?"]
    assert "web retrieval" in out
    assert "Sources:   2" in out
    assert "https://a.example.com" in out
    assert "The grounded answer." in out


def test_direct_route_rendering(configured, stub_pipeline, capsys):
    stub_pipeline(RESULT_DIRECT)
    cli.main(["What is 2+2?"])
    out = capsys.readouterr().out
    assert "direct model answer" in out
    assert "Sources:   0" in out


def test_ungrounded_answer_is_flagged(configured, stub_pipeline, capsys):
    """A fallback answer must not look source-backed."""
    stub_pipeline(RESULT_GROUNDED | {"grounded": False,
                                     "retrieval_status": "no_useful_results"})
    cli.main(["a query"])
    out = capsys.readouterr().out
    assert "Grounded:  NO" in out
    assert "did not support an answer" in out


def test_grounded_answer_is_marked(configured, stub_pipeline, capsys):
    stub_pipeline()
    cli.main(["a query"])
    assert "Grounded:  yes" in capsys.readouterr().out


# ---------------------------------------------------------------- errors
def test_pipeline_error_shows_a_readable_message(configured, stub_pipeline, capsys):
    stub_pipeline(error=RuntimeError("kaboom"))
    assert cli.main(["a query"]) == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert "Traceback" not in captured.err


def test_auth_error_is_explained(configured, stub_pipeline, capsys):
    class AuthenticationError(Exception):
        pass

    stub_pipeline(error=AuthenticationError("401"))
    cli.main(["a query"])
    assert "Authentication failed" in capsys.readouterr().err


def test_keyboard_interrupt_during_query_exits_130(configured, stub_pipeline, capsys):
    stub_pipeline(error=KeyboardInterrupt())
    assert cli.main(["a query"]) == 130
    assert "cancelled" in capsys.readouterr().out


# ------------------------------------------------------------------ REPL
def _feed(monkeypatch, answers):
    it = iter(answers)

    def fake_input(_prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    monkeypatch.setattr("builtins.input", fake_input)


@pytest.mark.parametrize("word", ["exit", "quit", "EXIT", ":q"])
def test_exit_words_quit_cleanly(configured, stub_pipeline, monkeypatch, capsys, word):
    calls = stub_pipeline()
    _feed(monkeypatch, [word])
    assert cli.main([]) == 0
    assert calls == [], "exit must not run a query"
    assert "Bye." in capsys.readouterr().out


def test_multiple_queries_in_one_session(configured, stub_pipeline, monkeypatch, capsys):
    calls = stub_pipeline()
    _feed(monkeypatch, ["first query", "second query", "exit"])
    assert cli.main([]) == 0
    assert calls == ["first query", "second query"]


def test_blank_input_is_ignored(configured, stub_pipeline, monkeypatch):
    calls = stub_pipeline()
    _feed(monkeypatch, ["", "   ", "real query", "exit"])
    cli.main([])
    assert calls == ["real query"]


def test_ctrl_c_at_prompt_exits_cleanly(configured, stub_pipeline, monkeypatch, capsys):
    stub_pipeline()

    def interrupt(_prompt=""):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupt)
    assert cli.main([]) == 0
    assert "Bye." in capsys.readouterr().out


def test_eof_exits_cleanly(configured, stub_pipeline, monkeypatch):
    stub_pipeline()
    _feed(monkeypatch, [])
    assert cli.main([]) == 0


def test_error_in_repl_does_not_end_the_session(configured, monkeypatch, capsys):
    """One failed query must not kill the prompt."""
    state = {"n": 0}

    async def flaky(query, *, openai_api_key, serper_api_key, trace=None):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("transient")
        return RESULT_DIRECT

    monkeypatch.setattr(cli, "run_query_pipeline", flaky)
    _feed(monkeypatch, ["one", "two", "exit"])

    assert cli.main([]) == 0
    assert state["n"] == 2


# -------------------------------------------------------------- rendering
def test_format_result_handles_missing_optional_fields():
    minimal = {"answer": "x", "used_search": False, "sources": [],
               "latency": 0.1, "routing_decision": "direct"}
    out = cli.format_result(minimal)
    assert "Answer:" in out and "x" in out


def test_format_result_handles_empty_answer():
    out = cli.format_result({"answer": "", "used_search": False, "sources": [],
                             "latency": 0.1, "routing_decision": "direct"})
    assert "(no answer returned)" in out
