"""LLM generation service."""

from __future__ import annotations

from openai import AsyncOpenAI


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
    for index, source in enumerate(sources[:3], start=1):
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

    if not blocks:
        return ""

    source_text = "\n\n".join(blocks)
    prompt = (
        "Answer using the provided sources as primary evidence.\n"
        "If some details are missing, provide the best possible answer and state uncertainty.\n"
        "Use citations like (Source 1).\n\n"
        f"Question:\n{query}\n\n"
        f"Sources:\n{source_text}"
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
