"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routes.query import router as query_router

app = FastAPI(
    title="AutoSearch-LLM API",
    description="Adaptive LLM routing with optional grounded web retrieval.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint for deployment probes."""
    return {"status": "ok"}
