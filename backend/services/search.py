"""Search + retrieval service."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from chunking import chunk_text
from ranker import CandidateChunk, score_chunks, select_top_chunks

from backend.services.scraper import extract_main_text, fetch_html

SERPER_ENDPOINT = "https://google.serper.dev/search"
logger = logging.getLogger(__name__)


def _truncate_words(text: str, max_words: int = 1200) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


async def discover_urls(
    query: str,
    *,
    serper_api_key: str,
    k: int = 8,
) -> list[dict[str, str | None]]:
    """Discover candidate URLs from Serper search."""
    payload: dict[str, Any] = {"q": query, "num": k, "gl": "us", "hl": "en"}
    headers = {"X-API-KEY": serper_api_key, "Content-Type": "application/json"}
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
    serper_api_key: str,
    k_search: int = 6,
    top_m: int = 3,
    deadline_ms: int = 4500,
    max_pages: int = 3,
) -> list[dict[str, Any]]:
    """
    End-to-end retrieval:
    search -> async scrape -> extraction -> chunking -> rank top chunks.
    """
    start = time.monotonic()
    deadline_s = start + (deadline_ms / 1000.0)

    try:
        candidates = await discover_urls(query, serper_api_key=serper_api_key, k=k_search)
    except RuntimeError:
        return []
    if not candidates:
        return []

    candidates = candidates[:max_pages]
    logger.info("retrieval: discovered_candidates=%s", len(candidates))

    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient() as client:
        async def fetch_one(candidate: dict[str, str | None]) -> list[CandidateChunk]:
            async with sem:
                if time.monotonic() >= deadline_s:
                    return []
                try:
                    html = await fetch_html(candidate["url"], client=client, timeout_s=4.0)
                    text = _truncate_words(extract_main_text(html), max_words=1200)
                    if len(text) < 220:
                        snippet = (candidate.get("snippet") or "").strip()
                        title = (candidate.get("title") or "").strip()
                        if len(snippet) < 60:
                            return []
                        text = f"{title}\n\n{snippet}".strip()

                    logger.info(
                        "retrieval: source_text_length=%s url=%s",
                        len(text),
                        candidate.get("url"),
                    )
                    chunks = [
                        CandidateChunk(
                            url=candidate["url"],
                            title=candidate.get("title"),
                            snippet=candidate.get("snippet"),
                            chunk_text=chunk,
                            chunk_index=idx,
                        )
                        for idx, chunk in enumerate(
                            chunk_text(
                                text,
                                max_chars=1200,
                                overlap_paragraphs=0,
                                min_chunk_chars=120,
                            )
                        )
                    ]
                    if chunks:
                        return chunks
                    return [
                        CandidateChunk(
                            url=candidate["url"],
                            title=candidate.get("title"),
                            snippet=candidate.get("snippet"),
                            chunk_text=text[:900],
                            chunk_index=0,
                        )
                    ]
                except Exception:
                    return []

        tasks = [asyncio.create_task(fetch_one(c)) for c in candidates if c.get("url")]
        if not tasks:
            return []
        done: list[asyncio.Task[list[CandidateChunk]]] = []
        pending = set(tasks)
        all_chunks: list[CandidateChunk] = []
        unique_urls: set[str] = set()

        while pending and time.monotonic() < deadline_s:
            remaining = max(0.0, deadline_s - time.monotonic())
            completed, pending = await asyncio.wait(
                pending,
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not completed:
                break

            for task in completed:
                done.append(task)
                if task.cancelled():
                    continue
                page_chunks = task.result()
                all_chunks.extend(page_chunks)
                for chunk in page_chunks:
                    unique_urls.add(chunk.url)

            # Early exit once we have enough context from multiple sources.
            if len(unique_urls) >= 3 and len(all_chunks) >= 6:
                break

        for task in pending:
            task.cancel()

    if not all_chunks:
        return []

    scored = score_chunks(query, all_chunks)
    selected = select_top_chunks(scored, top_m=top_m, max_chunks_per_domain=1)
    if len({chunk.url for chunk in selected}) < 2:
        seen_urls = {chunk.url for chunk in selected}
        for _, candidate in scored:
            if candidate.url in seen_urls:
                continue
            selected.append(candidate)
            seen_urls.add(candidate.url)
            if len(seen_urls) >= 2 or len(selected) >= top_m:
                break
        if len(seen_urls) < 2:
            for candidate in candidates:
                url = candidate.get("url")
                snippet = (candidate.get("snippet") or "").strip()
                if not url or url in seen_urls or len(snippet) < 60:
                    continue
                selected.append(
                    CandidateChunk(
                        url=url,
                        title=candidate.get("title"),
                        snippet=candidate.get("snippet"),
                        chunk_text=snippet,
                        chunk_index=0,
                    )
                )
                seen_urls.add(url)
                if len(seen_urls) >= 2:
                    break

    logger.info(
        "retrieval: scraped_sources=%s chunks_for_llm=%s",
        len({chunk.url for chunk in all_chunks}),
        len(selected),
    )
    results = [
        {
            "url": item.url,
            "title": item.title,
            "snippet": item.snippet,
            "chunk_text": item.chunk_text,
            "chunk_index": item.chunk_index,
        }
        for item in selected
    ]
    return results
