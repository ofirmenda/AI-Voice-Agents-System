"""HTTP wrapper around the embeddings CLI.

Exposes /health, /search and /ingest so the same retrieval used by the CLI is
callable from Vapi (voice agent custom tool) and Langflow (agent tool). The
response contract is stable: `results[0].text` is what downstream tool callers
parse.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app import (
    DEFAULT_MODEL,
    DEFAULT_STORE,
    build_index,
    get_client,
    load_index,
    rank_index,
)

logger = logging.getLogger("rag.api")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


class SearchBody(BaseModel):
    question: str = Field(..., description="Natural-language query (Hebrew or English).")
    top_k: int = Field(3, ge=1, le=20)


class SearchResult(BaseModel):
    text: str
    score: float


class SearchResponse(BaseModel):
    results: list[SearchResult]


class IngestBody(BaseModel):
    path: str = Field(..., min_length=1)


class IngestResponse(BaseModel):
    chunks: int


def _load_into_state(state: Any, store_path: Path) -> None:
    try:
        index = load_index(store_path)
    except FileNotFoundError:
        state.index = None
        state.source = ""
        logger.warning("no index at %s; /search will 503 until /ingest is called", store_path)
        return
    state.index = index
    state.source = index.get("source", str(store_path))
    logger.info("loaded index from %s (chunks=%d)", store_path, len(index["chunks"]))


def create_app(
    *,
    client: Any = None,
    store_path: str | Path | None = None,
    model: str = DEFAULT_MODEL,
) -> FastAPI:
    """Factory so tests can inject a stub embedding client and a temp store."""
    resolved_store = Path(store_path) if store_path is not None else Path(DEFAULT_STORE)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        _load_into_state(app.state, app.state.store_path)
        yield

    app = FastAPI(title="EL AL RAG service", lifespan=lifespan)
    app.state.store_path = resolved_store
    app.state.model = model
    app.state.client = client
    app.state.index = None
    app.state.source = ""

    def _client(request: Request):
        if request.app.state.client is None:
            request.app.state.client = get_client()
        return request.app.state.client

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        idx = request.app.state.index
        chunks = len(idx["chunks"]) if idx else 0
        return {"status": "ok", "chunks": chunks, "source": request.app.state.source}

    @app.post("/search", response_model=SearchResponse)
    def search(body: SearchBody, request: Request) -> SearchResponse:
        if not body.question.strip():
            raise HTTPException(status_code=422, detail="question must not be empty")
        idx = request.app.state.index
        if idx is None:
            raise HTTPException(
                status_code=503,
                detail="no index loaded; POST /ingest first",
            )
        started = time.perf_counter()
        ranked = rank_index(
            body.question,
            idx,
            _client(request),
            request.app.state.model,
            body.top_k,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "/search top_k=%d latency_ms=%.1f q=%r",
            body.top_k,
            latency_ms,
            body.question,
        )
        return SearchResponse(results=[SearchResult(**r) for r in ranked])

    @app.post("/ingest", response_model=IngestResponse)
    def ingest(body: IngestBody, request: Request) -> IngestResponse:
        source_path = Path(body.path)
        if not source_path.is_file():
            raise HTTPException(status_code=422, detail=f"file not found: {source_path}")
        chunks = build_index(
            source_path,
            request.app.state.store_path,
            _client(request),
            request.app.state.model,
        )
        _load_into_state(request.app.state, request.app.state.store_path)
        return IngestResponse(chunks=chunks)

    return app


app = create_app()
