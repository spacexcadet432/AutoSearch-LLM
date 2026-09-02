"""Query API route definitions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
)

from backend.models.query import QueryRequest, QueryResponse
from backend.services.credentials import resolve_llm_key, resolve_search_key
from backend.services.errors import RetrievalError
from backend.services.pipeline import run_query_pipeline

router = APIRouter(tags=["query"])
logger = logging.getLogger(__name__)


@router.post("/query", response_model=QueryResponse)
async def query_endpoint(
    payload: QueryRequest,
    x_openai_api_key: str | None = Header(default=None, alias="X-OpenAI-API-Key"),
    x_serper_api_key: str | None = Header(default=None, alias="X-Serper-API-Key"),
) -> QueryResponse:
    """Run adaptive query pipeline and return grounded response metadata.

    Error policy: every failure maps to a specific status code with a safe,
    fixed message. Provider exception text is logged server-side but never
    returned, since it can embed request URLs, org ids or key fragments.
    """
    # Request-supplied keys win; otherwise fall back to the server's own
    # credentials, which is how the EC2 deployment runs.
    openai_api_key = resolve_llm_key(payload.openai_api_key or x_openai_api_key)
    serper_api_key = resolve_search_key(payload.serper_api_key or x_serper_api_key)
    missing = [
        name
        for name, value in (("LLM", openai_api_key), ("Serper", serper_api_key))
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Missing credentials for: {', '.join(missing)}. Supply them in the "
                "request or configure them on the server."
            ),
        )

    try:
        result = await run_query_pipeline(
            payload.query,
            openai_api_key=openai_api_key,
            serper_api_key=serper_api_key,
        )
    except (AuthenticationError, PermissionDeniedError) as error:
        logger.warning("query: LLM auth rejected (%s)", type(error).__name__)
        raise HTTPException(status_code=401, detail="Invalid LLM API key.") from error
    except RateLimitError as error:
        logger.warning("query: LLM rate limited")
        raise HTTPException(
            status_code=429,
            detail="LLM provider rate limit reached. Please retry shortly.",
        ) from error
    except APITimeoutError as error:
        logger.warning("query: LLM timed out")
        raise HTTPException(
            status_code=504, detail="LLM provider timed out."
        ) from error
    except APIConnectionError as error:
        logger.warning("query: cannot reach LLM provider (%s)", type(error).__name__)
        raise HTTPException(
            status_code=502, detail="Could not reach the LLM provider."
        ) from error
    except BadRequestError as error:
        # e.g. context too long, or a model id the provider does not serve.
        logger.warning("query: LLM rejected the request (%s)", error)
        raise HTTPException(
            status_code=502, detail="LLM provider rejected the request."
        ) from error
    except APIStatusError as error:
        logger.warning("query: LLM provider error status=%s", error.status_code)
        raise HTTPException(
            status_code=502, detail="LLM provider returned an error."
        ) from error
    except RetrievalError as error:
        # Retrieval degrades internally, so reaching here means it could not
        # degrade any further.
        logger.warning("query: retrieval failed (%s)", error)
        raise HTTPException(
            status_code=503, detail="Web retrieval is currently unavailable."
        ) from error
    except Exception as error:  # noqa: BLE001
        # Genuinely unexpected: log the full traceback for diagnosis, return a
        # generic message so no internal detail or stack trace reaches the user.
        logger.exception("query: unhandled error processing request")
        raise HTTPException(
            status_code=500,
            detail="Query processing failed. Please try again.",
        ) from error

    return QueryResponse(**result)
