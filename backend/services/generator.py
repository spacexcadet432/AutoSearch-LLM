"""LLM generation service."""

from __future__ import annotations

import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


async def generate_standard_answer(query: str, api_key: str) -> str:
    """Generate a direct answer without retrieval context."""
    client = AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a concise helpful assistant."},
            {"role": "user", "content": query},
        ],
        temperature=0.3,
    )
    return response.choices[0].message.content or ""


async def generate_grounded_answer(query: str, sources: list[dict], api_key: str) -> str:
    """Generate answer grounded only in retrieved source chunks."""
    client = AsyncOpenAI(api_key=api_key)
    blocks: list[str] = []
    for index, source in enumerate(sources[:2], start=1):
        chunk = (source.get("chunk_text") or "").strip()
        if not chunk:
            continue
        blocks.append(
            (
                f"Source {index}\n"
                f"Title: {source.get('title') or 'N/A'}\n"
                f"URL: {source.get('url')}\n"
                f"Chunk: {chunk[:900]}"
            )
        )

    supporting_sources: list[str] = []
    for source in sources[2:4]:
        url = (source.get("url") or "").strip()
        snippet = (source.get("snippet") or "").strip()
        if url:
            supporting_sources.append(f"- {url}: {snippet[:220]}")

    logger.info("generation: chunks_passed_to_llm=%s", len(blocks))
    if not blocks:
        return ""

    source_text = "\n\n".join(blocks)
    corroboration = "\n".join(supporting_sources)
    prompt = (
        "Generate a clear, specific answer using the provided context.\n"
        "List concrete developments, facts, or trends.\n"
        "Avoid vague language such as: suggests, anticipated, may, might.\n"
        "Use this structure:\n"
        "1) One-sentence intro\n"
        "2) Bullet points with concrete facts and citations\n"
        "3) Short conclusion\n"
        "Use citations like (Source 1), (Source 2).\n\n"
        f"Question:\n{query}\n\n"
        f"Primary Sources:\n{source_text}\n\n"
        f"Additional corroboration:\n{corroboration or 'None'}"
    )

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You strictly ground claims in sources."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )
    return response.choices[0].message.content or ""
