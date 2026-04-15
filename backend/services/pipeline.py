"""Main query orchestration service."""

from __future__ import annotations

import logging
import time
from typing import Any

from backend.services.generator import generate_grounded_answer, generate_standard_answer
from backend.services.routing import classify_temporal_need
from backend.services.search import retrieve_sources

logger = logging.getLogger(__name__)


async def run_query_pipeline(
    query: str,
    *,
    openai_api_key: str,
    serper_api_key: str,
) -> dict[str, Any]:
    """Run adaptive route -> retrieval (optional) -> generation pipeline."""
    start = time.perf_counter()

    needs_search, confidence = await classify_temporal_need(query, openai_api_key)
    if needs_search:
        source_chunks = await retrieve_sources(
            query,
            serper_api_key=serper_api_key,
            max_pages=3,
            top_m=3,
            deadline_ms=3500,
        )
        logger.info(
            "pipeline: retrieval_result_sources=%s",
            len({s.get("url") for s in source_chunks if s.get("url")}),
        )
        if source_chunks:
            answer = await generate_grounded_answer(query, source_chunks, openai_api_key)
            if not answer.strip() or "insufficient verified information" in answer.lower():
                answer = await generate_standard_answer(query, openai_api_key)
        else:
            answer = await generate_standard_answer(query, openai_api_key)
        sources = list(dict.fromkeys(s["url"] for s in source_chunks if s.get("url")))
        if len(sources) < 2:
            extra_sources = [s["url"] for s in source_chunks if s.get("url")]
            for url in extra_sources:
                if url not in sources:
                    sources.append(url)
                if len(sources) >= 2:
                    break
        routing_decision = "search"
    else:
        answer = await generate_standard_answer(query, openai_api_key)
        sources = []
        routing_decision = "direct"

    latency = round(time.perf_counter() - start, 3)
    return {
        "answer": answer,
        "used_search": needs_search,
        "sources": sources,
        "latency": latency,
        "routing_decision": routing_decision,
        "confidence": round(confidence, 3) if confidence is not None else None,
    }
