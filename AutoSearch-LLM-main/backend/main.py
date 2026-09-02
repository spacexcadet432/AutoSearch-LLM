"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.logging_config import configure_logging
from backend.routes.query import router as query_router
from backend.services import config
from backend.services.cache import get_search_cache
from backend.services.credentials import server_credentials_present

configure_logging()
logger = logging.getLogger("autosearch")

_STARTED_AT = time.monotonic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Log a non-secret startup summary and shut down cleanly."""
    summary = config.public_config_summary()
    creds = server_credentials_present()
    logger.info("startup: AutoSearch-LLM starting")
    for key, value in summary.items():
        logger.info("startup: %s=%s", key, value)
    # Booleans only - credential values are never logged.
    logger.info(
        "startup: server_credentials llm=%s search=%s (requests may also supply their own)",
        creds["llm"], creds["search"],
    )
    if not creds["llm"] and not creds["search"]:
        logger.warning(
            "startup: no server-side credentials configured; every request must "
            "supply its own API keys"
        )
    # Misconfiguration should be loud rather than silent in production.
    if config.is_production() and config.allowed_origins() == ["*"]:
        logger.warning(
            "startup: AUTOSEARCH_ALLOWED_ORIGINS is '*' in production; set it to "
            "the origin(s) that will call this API"
        )
    try:
        yield
    finally:
        # In-flight retrieval tasks are cancelled by their own request scope
        # (see backend/services/search.py), so there is nothing to drain here.
        logger.info(
            "shutdown: cache_stats=%s uptime_s=%.1f",
            get_search_cache().stats(),
            time.monotonic() - _STARTED_AT,
        )
        logger.info("shutdown: complete")


_docs_enabled = config.enable_docs()

app = FastAPI(
    title="AutoSearch-LLM API",
    description="Adaptive LLM routing with optional grounded web retrieval.",
    version="3.0.0",
    lifespan=lifespan,
    # Disabled in production: these are live debugging consoles.
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

_origins = config.allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # Credentialed requests cannot be combined with a wildcard origin; browsers
    # reject it. Auth here is a header-supplied API key, not a cookie, so
    # credentials are simply not needed with an open origin.
    allow_credentials=_origins != ["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Request log with latency. Never logs headers, bodies or query strings."""
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - started) * 1000
        logger.exception(
            "request: %s %s failed after %.1fms",
            request.method, request.url.path, duration_ms,
        )
        raise
    duration_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "request: %s %s -> %s in %.1fms",
        request.method, request.url.path, response.status_code, duration_ms,
    )
    return response


app.include_router(query_router)


@app.get("/health")
async def health() -> dict[str, Any]:
    """Liveness/readiness probe.

    Cheap by design: reports only in-process state and configuration. It makes
    no call to Bedrock or Serper, so probing it never costs quota and a
    provider outage never marks the instance unhealthy.
    """
    creds = server_credentials_present()
    return {
        "status": "ok",
        "version": app.version,
        "environment": config.environment(),
        "uptime_s": round(time.monotonic() - _STARTED_AT, 1),
        "credentials_configured": creds,
        "cache": get_search_cache().stats(),
    }
