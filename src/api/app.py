"""FastAPI application factory.

Middleware order (outermost first):
1. Request context (assigns X-Request-ID, logs access lines).
2. CORS (optional).
3. SlowAPI rate limiter (raises RateLimitExceeded, handled below).

Exception handlers translate domain errors and unexpected exceptions into
the canonical error envelope defined in :mod:`src.api.errors`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from src.api.errors import (
    ApiError,
    api_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from src.api.logging import RequestContextMiddleware, configure_logging, get_logger
from src.api.metadata_cache import build_snapshot_from_rows
from src.api.rate_limit import limiter, rate_limit_handler
from src.api.routes import build_v1_router
from src.api.settings import Settings, get_settings


def _attempt_startup_metadata() -> None:
    """Best-effort populate metadata cache; never block startup on Qdrant outage."""
    from src.api.deps import _metadata_cache_singleton, _qdrant_store_singleton
    from src.storage.qdrant_store import YieldFilter

    log = get_logger("api.startup")
    try:
        store = _qdrant_store_singleton()
        rows = list(store.iter_yield_rows(YieldFilter()))
        snapshot = build_snapshot_from_rows(rows)
        _metadata_cache_singleton().set(snapshot)
        log.info(
            "metadata.loaded",
            regions=snapshot.regions_count,
            provinces=snapshot.provinces_count,
            years=snapshot.years_count,
        )
    except Exception as exc:
        log.warning(
            "metadata.load_failed",
            reason=exc.__class__.__name__,
            hint="Call POST /v1/index/refresh-metadata after Qdrant is reachable.",
        )


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    _attempt_startup_metadata()
    yield


_API_DESCRIPTION = """
PRiSM rice yield + PSA OpenSTAT farmgate price API — versioned under `/v1/`.

This service exposes scraped datasets over HTTP, backed by Qdrant:

- **Yield structured queries** (`/v1/yield`, `/v1/yield/metadata`, `/v1/yield/summary`, `/v1/yield/export`).
- **Yield hybrid search** (`/v1/knowledge/search`).
- **OpenSTAT price structured queries** (`/v1/prices`, `/v1/prices/metadata`, `/v1/prices/summary`, `/v1/prices/export`).
- **OpenSTAT price hybrid search** (`/v1/prices/search`).
- **Narrative agri corpus search** (`/v1/corpus/search` — PhilRice, News, PinoyRice, IRRI, PRiSM browser).
- **Operator endpoints** (`/v1/index/status`, `/v1/index/refresh-metadata`, `/v1/prices/refresh-metadata`).

Authentication uses `X-API-Key`. Two scopes: **public** (read endpoints) and
**admin** (export + index admin). Set `API_AUTH_DISABLED=true` to bypass during
local development. Errors follow a uniform envelope:
`{"error": {"code": "...", "message": "...", "details": {...}}}`.
""".strip()

_OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Liveness / connectivity probes. No auth required.",
    },
    {
        "name": "yield",
        "description": (
            "Structured queries over the scraped yield dataset: paginated list, "
            "filter metadata, deterministic aggregation, and bulk export."
        ),
    },
    {
        "name": "prices",
        "description": (
            "Structured queries over PSA OpenSTAT farmgate prices: paginated list, "
            "filter metadata, deterministic aggregation, export, and hybrid search."
        ),
    },
    {
        "name": "knowledge",
        "description": (
            "Hybrid (dense + sparse) semantic search for natural-language queries. "
            "Pure retrieval — no summarization or LLM generation in this version."
        ),
    },
    {
        "name": "corpus",
        "description": (
            "Hybrid semantic search over the unified agri RAG corpus "
            "(PhilRice, News, PinoyRice, IRRI, PRiSM browser chunks)."
        ),
    },
    {
        "name": "admin",
        "description": (
            "Operator endpoints: index counts, source freshness, in-memory cache rebuild."
        ),
    },
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    docs_url = "/v1/docs" if settings.api_docs_enabled else None
    redoc_url = "/v1/redoc" if settings.api_docs_enabled else None
    openapi_url = "/v1/openapi.json" if settings.api_docs_enabled else None

    app = FastAPI(
        title=settings.api_title,
        version=settings.api_version,
        description=_API_DESCRIPTION,
        openapi_tags=_OPENAPI_TAGS,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=_lifespan,
    )

    app.state.limiter = limiter
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "X-API-Key", "Content-Type"],
        )

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)

    app.include_router(build_v1_router())

    return app


app = create_app()
