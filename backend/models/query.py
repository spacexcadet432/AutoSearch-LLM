"""Pydantic models for query endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """Incoming request body for adaptive query endpoint."""

    query: str = Field(..., min_length=2, description="User question")
    api_key: str | None = Field(
        default=None,
        description="Optional OpenAI API key supplied by user per request.",
    )


class QueryResponse(BaseModel):
    """Structured API response for frontend rendering."""

    answer: str
    used_search: bool
    sources: list[str]
    latency: float
    routing_decision: str
    confidence: float | None = None
