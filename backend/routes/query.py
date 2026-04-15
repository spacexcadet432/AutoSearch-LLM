"""Query API route definitions."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from openai import AuthenticationError

from backend.models.query import QueryRequest, QueryResponse
from backend.services.pipeline import run_query_pipeline

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(
    payload: QueryRequest,
    x_openai_api_key: str | None = Header(default=None, alias="X-OpenAI-API-Key"),
    x_serper_api_key: str | None = Header(default=None, alias="X-Serper-API-Key"),
) -> QueryResponse:
    """Run adaptive query pipeline and return grounded response metadata."""
    try:
        openai_api_key = (payload.openai_api_key or x_openai_api_key or "").strip()
        serper_api_key = (payload.serper_api_key or x_serper_api_key or "").strip()
        if not openai_api_key or not serper_api_key:
            raise HTTPException(
                status_code=400,
                detail="Both OpenAI and Serper API keys are required",
            )

        result = await run_query_pipeline(
            payload.query,
            openai_api_key=openai_api_key,
            serper_api_key=serper_api_key,
        )
        return QueryResponse(**result)
    except HTTPException:
        raise
    except AuthenticationError as error:
        raise HTTPException(status_code=401, detail="Invalid OpenAI API key.") from error
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail="Query processing failed. Please try again.",
        ) from error
