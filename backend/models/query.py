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
    """Structured API response for frontend rendering."""

    answer: str
    used_search: bool
    sources: list[str]
    latency: float
    routing_decision: str
    confidence: float | None = None
