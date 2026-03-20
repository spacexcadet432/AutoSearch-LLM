import asyncio
import time
from typing import Any, Optional

import httpx

from chunking import chunk_text
from ranker import CandidateChunk, select_top_chunks, score_chunks
from search import discover_urls
from scraper import extract_main_text, fetch_html


async def retrieve_sources(
    query: str,
    *,
    k_search: int = 10,
    top_m: int = 8,
    deadline_ms: int = 2500,
    fetch_timeout_s: float = 8.0,
    extract_min_chars: int = 400,
    max_pages: int = 8,
    max_fetch_concurrency: int = 6,
    max_download_bytes: int = 1_500_000,
) -> list[dict[str, Any]]:
    """
    End-to-end retrieval:
    query -> URL discovery (Serper) -> async fetch -> readability extraction -> chunking -> ranking -> top chunks.

    Returns list of dicts: {url, title, chunk_text, chunk_index, snippet}
    """
    start = time.monotonic()
    deadline_s = start + (deadline_ms / 1000.0)

    # Stage 1: URL discovery
    # Give discovery more time because it is a network API call.
    time_left = max(0.0, deadline_s - time.monotonic())
    discovery_deadline = min(4.0, time_left)

    try:
        # Serper uses httpx internally; bound discovery by remaining time.
        candidates = await asyncio.wait_for(discover_urls(query, k=k_search), timeout=discovery_deadline)
    except asyncio.TimeoutError:
        return []
    except Exception:
        return []

    if not candidates:
        return []

    candidates = candidates[:max_pages]

    # Stage 2: concurrent fetch + extract
    sem = asyncio.Semaphore(max_fetch_concurrency)

    async with httpx.AsyncClient() as client:
        async def one(url: str, title: Optional[str], snippet: Optional[str]) -> list[CandidateChunk]:
            async with sem:
                # Check deadline cooperatively.
                if time.monotonic() >= deadline_s:
                    return []

                try:
                    html = await fetch_html(
                        url,
                        client=client,
                        timeout_s=fetch_timeout_s,
                        max_bytes=max_download_bytes,
                    )
                    text = extract_main_text(html)
                    if not text or len(text) < extract_min_chars:
                        return []

                    pieces = chunk_text(text)
                    # Build CandidateChunk objects per chunk.
                    chunks: list[CandidateChunk] = []
                    for idx, p in enumerate(pieces):
                        chunks.append(
                            CandidateChunk(
                                url=url,
                                title=title,
                                chunk_text=p,
                                chunk_index=idx,
                                snippet=snippet,
                            )
                        )
                    return chunks
                except Exception:
                    return []

        tasks = [
            asyncio.create_task(one(c["url"], c.get("title"), c.get("snippet")))
            for c in candidates
            if c.get("url")
        ]

        # Wait for tasks but respect deadline.
        remaining = max(0.0, deadline_s - time.monotonic())
        done, pending = await asyncio.wait(tasks, timeout=remaining)
        for t in pending:
            t.cancel()

        # `one()` swallows internal exceptions and returns [] on failure,
        # so results from completed tasks are safe to collect.
        fetched_pages = [t.result() for t in done if not t.cancelled()]

    all_chunks: list[CandidateChunk] = []
    for page_chunks in fetched_pages:
        all_chunks.extend(page_chunks)

    if not all_chunks:
        return []

    # Stage 3: rank chunks, return top_m with diversity.
    scored = score_chunks(query, all_chunks)
    selected = select_top_chunks(scored, top_m=top_m, max_chunks_per_domain=2)

    # Convert to serializable dict form.
    results: list[dict[str, Any]] = []
    for c in selected:
        results.append(
            {
                "url": c.url,
                "title": c.title,
                "chunk_text": c.chunk_text,
                "chunk_index": c.chunk_index,
                "snippet": c.snippet,
            }
        )
    return results

