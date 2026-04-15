"""Query API route definitions."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from openai import AuthenticationError

from backend.models.query import QueryRequest, QueryResponse
from backend.services.pipeline import run_query_pipeline
from backend.utils.config import resolve_openai_api_key

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(
    payload: QueryRequest,
    x_openai_api_key: str | None = Header(default=None, alias="X-OpenAI-API-Key"),
) -> QueryResponse:
    """Run adaptive query pipeline and return grounded response metadata."""
    try:
        api_key = resolve_openai_api_key(payload.api_key or x_openai_api_key)
        result = await run_query_pipeline(payload.query, api_key)
        return QueryResponse(**result)
    except AuthenticationError as error:
        raise HTTPException(status_code=401, detail="Invalid OpenAI API key.") from error
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="Query processing failed. Please try again.",
        ) from error
