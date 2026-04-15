"""Main query orchestration service."""

from __future__ import annotations

import time
from typing import Any

from backend.services.generator import generate_grounded_answer, generate_standard_answer
from backend.services.routing import classify_temporal_need
from backend.services.search import retrieve_sources


async def run_query_pipeline(query: str, api_key: str) -> dict[str, Any]:
    """Run adaptive route -> retrieval (optional) -> generation pipeline."""
    start = time.perf_counter()

    needs_search, confidence = await classify_temporal_need(query, api_key)
    if needs_search:
        source_chunks = await retrieve_sources(query, max_pages=5, top_m=6)
        if source_chunks:
            answer = await generate_grounded_answer(query, source_chunks, api_key)
        else:
            answer = "Insufficient verified information."
        sources = list(dict.fromkeys(s["url"] for s in source_chunks if s.get("url")))
        routing_decision = "search"
    else:
        answer = await generate_standard_answer(query, api_key)
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
