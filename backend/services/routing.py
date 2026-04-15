"""Temporal routing service."""

from __future__ import annotations

import json

from openai import AsyncOpenAI


async def classify_temporal_need(query: str, api_key: str) -> tuple[bool, float]:
    """
    Decide if query needs fresh web data.

    Returns:
        tuple[needs_search, confidence]
    """
    client = AsyncOpenAI(api_key=api_key)
    prompt = f"""
You are a strict classifier.

Task:
Determine whether this query requires current, post-training data to answer correctly.

Output format (JSON only):
{{"decision":"search"|"direct","confidence":0.0-1.0}}

Query:
{query}
"""

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a precise routing classifier."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}

    decision = str(parsed.get("decision", "direct")).strip().lower()
    confidence_raw = parsed.get("confidence", 0.7)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.7
    confidence = max(0.0, min(1.0, confidence))

    return decision == "search", confidence
