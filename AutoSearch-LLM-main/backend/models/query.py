"""Pydantic models for query endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Incoming request body for adaptive query endpoint."""

    query: str = Field(..., min_length=2, description="User question")
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key supplied per request.",
    )
    serper_api_key: str | None = Field(
        default=None,
        description="Serper API key supplied per request.",
    )


class QueryResponse(BaseModel):
    """Structured API response for frontend rendering.

    ``retrieval_status`` and ``grounded`` were added for reliability reporting.
    Both are optional with backwards-compatible defaults, so existing clients
    that ignore them keep working unchanged.
    """

    answer: str
    used_search: bool
    sources: list[str]
    latency: float
    routing_decision: str
    confidence: float | None = None
    retrieval_status: str | None = Field(
        default=None,
        description=(
            "Retrieval outcome when search was used: 'ok' (all sources fetched), "
            "'partial' (some sources failed), 'no_results' (nothing usable found), "
            "'no_useful_results' (sources found but they did not support an answer), "
            "or 'failed' (search provider unavailable). Null when routed direct."
        ),
    )
    grounded: bool = Field(
        default=False,
        description=(
            "True only when the answer was generated from retrieved sources. "
            "False means the answer came from model knowledge, even if "
            "`sources` is non-empty and `used_search` is true."
        ),
    )
