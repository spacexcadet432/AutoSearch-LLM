"""Main query orchestration service."""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.services.generator import generate_grounded_answer, generate_standard_answer
from backend.services.routing import classify_temporal_need
from backend.services.search import retrieve_sources

logger = logging.getLogger(__name__)

# Marker the grounded prompt is instructed to emit when the sources do not
# support an answer.
_INSUFFICIENT_MARKER = "insufficient verified information"


async def run_query_pipeline(
    query: str,
    *,
    openai_api_key: str,
    serper_api_key: str,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run adaptive route -> retrieval (optional) -> generation pipeline.

    Degradation policy: retrieval failing does not fail the request. The system
    falls back to an ungrounded answer, but reports that honestly via
    ``grounded=False`` rather than presenting model recall as source-backed.

    If ``trace`` is provided it is populated in place with per-stage latencies
    (milliseconds) and retrieval diagnostics. It never changes the returned
    payload, so the API response contract is unaffected.
    """
    start = time.perf_counter()

    def record(**fields: Any) -> None:
        if trace is not None:
            trace.update(fields)

    routing_start = time.perf_counter()
    needs_search, confidence = await classify_temporal_need(query, openai_api_key)
    record(
        routing_ms=round((time.perf_counter() - routing_start) * 1000, 1),
        retrieval_ms=0.0,
    )

    retrieval_status: str | None = None
    grounded = False

    if needs_search:
        retrieval_stats: dict[str, Any] = {}
        retrieval_start = time.perf_counter()
        source_chunks = await retrieve_sources(
            query,
            serper_api_key=serper_api_key,
            max_pages=3,
            top_m=3,
            stats=retrieval_stats,
        )
        record(
            retrieval_ms=round((time.perf_counter() - retrieval_start) * 1000, 1),
            retrieval=retrieval_stats,
        )
        retrieval_status = retrieval_stats.get("status") or (
            "ok" if source_chunks else "failed"
        )
        logger.info(
            "pipeline: retrieval_status=%s sources=%s",
            retrieval_status,
            len({s.get("url") for s in source_chunks if s.get("url")}),
        )

        generation_start = time.perf_counter()
        if source_chunks:
            answer = await generate_grounded_answer(query, source_chunks, openai_api_key)
            generation_mode = "grounded"
            grounded = True
            if not answer.strip() or _INSUFFICIENT_MARKER in answer.lower():
                # The sources did not support an answer. We still answer, but
                # the result is model recall, NOT grounded in these sources -
                # so it must not be presented as source-backed.
                answer = await generate_standard_answer(query, openai_api_key)
                generation_mode = "grounded_fallback_direct"
                grounded = False
                if retrieval_status in ("ok", "partial"):
                    retrieval_status = "no_useful_results"
        else:
            answer = await generate_standard_answer(query, openai_api_key)
            generation_mode = "no_sources_fallback_direct"
            grounded = False
        record(
            generation_ms=round((time.perf_counter() - generation_start) * 1000, 1),
            generation_mode=generation_mode,
        )
        # dict.fromkeys preserves rank order while de-duplicating.
        sources = list(dict.fromkeys(s["url"] for s in source_chunks if s.get("url")))
        routing_decision = "search"
    else:
        generation_start = time.perf_counter()
        answer = await generate_standard_answer(query, openai_api_key)
        record(
            generation_ms=round((time.perf_counter() - generation_start) * 1000, 1),
            generation_mode="direct",
        )
        sources = []
        routing_decision = "direct"

    latency = round(time.perf_counter() - start, 3)
    record(
        total_ms=round(latency * 1000, 1),
        routing_decision=routing_decision,
        used_search=needs_search,
        confidence=confidence,
        source_count=len(sources),
        retrieval_status=retrieval_status,
        grounded=grounded,
    )
    return {
        "answer": answer,
        "used_search": needs_search,
        "sources": sources,
        "latency": latency,
        "routing_decision": routing_decision,
        "confidence": round(confidence, 3) if confidence is not None else None,
        "retrieval_status": retrieval_status,
        "grounded": grounded,
    }
