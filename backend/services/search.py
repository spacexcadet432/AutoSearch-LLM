"""Search + retrieval service."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from chunking import chunk_text
from ranker import CandidateChunk, score_chunks, select_top_chunks

from backend.services.scraper import extract_main_text, fetch_html
from backend.utils.config import get_serper_api_key

SERPER_ENDPOINT = "https://google.serper.dev/search"


async def discover_urls(query: str, k: int = 8) -> list[dict[str, str | None]]:
    """Discover candidate URLs from Serper search."""
    api_key = get_serper_api_key()
    payload: dict[str, Any] = {"q": query, "num": k, "gl": "us", "hl": "en"}
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    timeout = httpx.Timeout(10.0, connect=5.0)

    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            response = await client.post(SERPER_ENDPOINT, json=payload)
            if response.status_code != 200:
                raise RuntimeError(f"Search provider error: {response.status_code}")
            organic = response.json().get("organic", []) or []
    except httpx.TimeoutException as error:
        raise RuntimeError("Search provider timed out.") from error
    except httpx.HTTPError as error:
        raise RuntimeError("Search provider request failed.") from error

    deduped: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for item in organic:
        url = item.get("link")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(
            {"url": url, "title": item.get("title"), "snippet": item.get("snippet")}
        )
        if len(deduped) >= k:
            break
    return deduped


async def retrieve_sources(
    query: str,
    *,
    k_search: int = 8,
    top_m: int = 6,
    deadline_ms: int = 5000,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    """
    End-to-end retrieval:
    search -> async scrape -> extraction -> chunking -> rank top chunks.
    """
    start = time.monotonic()
    deadline_s = start + (deadline_ms / 1000.0)

    try:
        candidates = await discover_urls(query, k=k_search)
    except RuntimeError:
        return []
    if not candidates:
        return []

    candidates = candidates[:max_pages]
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient() as client:
        async def fetch_one(candidate: dict[str, str | None]) -> list[CandidateChunk]:
            async with sem:
                if time.monotonic() >= deadline_s:
                    return []
                try:
                    html = await fetch_html(candidate["url"], client=client, timeout_s=8.0)
                    text = extract_main_text(html)
                    if len(text) < 350:
                        return []
                    return [
                        CandidateChunk(
                            url=candidate["url"],
                            title=candidate.get("title"),
                            snippet=candidate.get("snippet"),
                            chunk_text=chunk,
                            chunk_index=idx,
                        )
                        for idx, chunk in enumerate(chunk_text(text))
                    ]
                except Exception:
                    return []

        tasks = [asyncio.create_task(fetch_one(c)) for c in candidates if c.get("url")]
        if not tasks:
            return []
        remaining = max(0.0, deadline_s - time.monotonic())
        done, pending = await asyncio.wait(tasks, timeout=remaining)
        for task in pending:
            task.cancel()

    all_chunks: list[CandidateChunk] = []
    for task in done:
        if not task.cancelled():
            all_chunks.extend(task.result())
    if not all_chunks:
        return []

    selected = select_top_chunks(score_chunks(query, all_chunks), top_m=top_m)
    return [
        {
            "url": item.url,
            "title": item.title,
            "snippet": item.snippet,
            "chunk_text": item.chunk_text,
            "chunk_index": item.chunk_index,
        }
        for item in selected
    ]
