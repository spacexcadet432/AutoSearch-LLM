"""Pipeline degradation and grounding-honesty tests."""

from __future__ import annotations

import pytest

import backend.services.pipeline as pipeline


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Stub routing, retrieval and generation; return a call recorder."""
    calls: dict = {"grounded": 0, "standard": 0}

    def _install(*, needs_search=True, sources=None, stats=None,
                 grounded_answer="A grounded answer.", standard_answer="A direct answer."):
        async def classify(query, api_key):
            return needs_search, 0.9

        async def retrieve(query, *, serper_api_key, max_pages=3, top_m=3, stats=None, **kw):
            if stats is not None and _install.stats:
                stats.update(_install.stats)
            return _install.sources

        async def gen_grounded(query, srcs, api_key):
            calls["grounded"] += 1
            if isinstance(grounded_answer, Exception):
                raise grounded_answer
            return grounded_answer

        async def gen_standard(query, api_key):
            calls["standard"] += 1
            if isinstance(standard_answer, Exception):
                raise standard_answer
            return standard_answer

        _install.sources = sources if sources is not None else []
        _install.stats = stats or {}
        monkeypatch.setattr(pipeline, "classify_temporal_need", classify)
        monkeypatch.setattr(pipeline, "retrieve_sources", retrieve)
        monkeypatch.setattr(pipeline, "generate_grounded_answer", gen_grounded)
        monkeypatch.setattr(pipeline, "generate_standard_answer", gen_standard)
        return calls

    return _install


async def _run():
    return await pipeline.run_query_pipeline(
        "a query", openai_api_key="k", serper_api_key="s"
    )


SOURCES = [{"url": "https://a.example.com", "title": "t", "snippet": "s", "chunk_text": "text"}]


async def test_successful_grounded_answer_is_marked_grounded(stub_pipeline):
    stub_pipeline(sources=SOURCES, stats={"status": "ok"})
    result = await _run()

    assert result["grounded"] is True
    assert result["retrieval_status"] == "ok"
    assert result["used_search"] is True
    assert result["sources"] == ["https://a.example.com"]


async def test_partial_retrieval_is_reported_as_partial(stub_pipeline):
    stub_pipeline(sources=SOURCES, stats={"status": "partial"})
    result = await _run()

    assert result["grounded"] is True
    assert result["retrieval_status"] == "partial"


async def test_no_sources_falls_back_to_direct_and_is_not_grounded(stub_pipeline):
    """Retrieval failure must degrade to an answer, not a 500."""
    calls = stub_pipeline(sources=[], stats={"status": "failed"})
    result = await _run()

    assert result["answer"] == "A direct answer."
    assert result["grounded"] is False
    assert result["sources"] == []
    assert result["retrieval_status"] == "failed"
    assert calls["standard"] == 1 and calls["grounded"] == 0


async def test_insufficient_grounding_is_not_presented_as_source_backed(stub_pipeline):
    """The key honesty case: model recall must never be labelled grounded."""
    calls = stub_pipeline(
        sources=SOURCES,
        stats={"status": "ok"},
        grounded_answer="Insufficient verified information.",
    )
    result = await _run()

    assert result["answer"] == "A direct answer."
    assert result["grounded"] is False, "ungrounded answer must not claim grounding"
    assert result["retrieval_status"] == "no_useful_results"
    assert calls["grounded"] == 1 and calls["standard"] == 1


async def test_empty_grounded_answer_also_falls_back(stub_pipeline):
    stub_pipeline(sources=SOURCES, stats={"status": "ok"}, grounded_answer="   ")
    result = await _run()
    assert result["answer"] == "A direct answer."
    assert result["grounded"] is False


async def test_direct_route_skips_retrieval_entirely(stub_pipeline):
    calls = stub_pipeline(needs_search=False)
    result = await _run()

    assert result["routing_decision"] == "direct"
    assert result["used_search"] is False
    assert result["retrieval_status"] is None
    assert result["grounded"] is False
    assert calls["grounded"] == 0


async def test_llm_failure_propagates_rather_than_returning_a_fake_answer(stub_pipeline):
    """A generation failure must surface, not be masked with invented content."""
    stub_pipeline(needs_search=False, standard_answer=RuntimeError("llm down"))
    with pytest.raises(RuntimeError, match="llm down"):
        await _run()


async def test_trace_captures_stage_timings(stub_pipeline):
    stub_pipeline(sources=SOURCES, stats={"status": "ok"})
    trace: dict = {}
    await pipeline.run_query_pipeline(
        "a query", openai_api_key="k", serper_api_key="s", trace=trace
    )

    for key in ("routing_ms", "retrieval_ms", "generation_ms", "total_ms"):
        assert isinstance(trace[key], float)
    assert trace["generation_mode"] == "grounded"
    assert trace["grounded"] is True


async def test_sources_are_deduplicated_preserving_rank_order(stub_pipeline):
    stub_pipeline(
        sources=[
            {"url": "https://b.example.com", "chunk_text": "x"},
            {"url": "https://a.example.com", "chunk_text": "y"},
            {"url": "https://b.example.com", "chunk_text": "z"},
        ],
        stats={"status": "ok"},
    )
    result = await _run()
    assert result["sources"] == ["https://b.example.com", "https://a.example.com"]
