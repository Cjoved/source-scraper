"""Knowledge search route: pure hybrid (dense + sparse) semantic retrieval.

This endpoint does **not** route to summary/list backends; callers (and the
future LLM agent) decide which tool to invoke. Response shape is stable.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_public
from src.api.deps import get_qdrant_store
from src.api.limit_config import rate_limit_search
from src.api.rate_limit import limiter
from src.api.schemas import (
    KnowledgeHit,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    SemesterCode,
)
from src.services.filters import filter_from_knowledge_filters
from src.storage.qdrant_store import KnowledgeHitRecord, QdrantStoreProtocol

router = APIRouter(tags=["knowledge"])


def _hit_record_to_schema(record: KnowledgeHitRecord) -> KnowledgeHit | None:
    payload = record.payload
    try:
        return KnowledgeHit(
            score=record.score,
            text=str(payload.get("text") or ""),
            year=int(payload["year"]),
            semester_code=SemesterCode(int(payload["semester_code"])),
            semester_label=str(payload.get("semester_label") or ""),
            region=str(payload.get("region") or ""),
            province=str(payload.get("province") or ""),
            municipality=str(payload.get("municipality") or ""),
            avg_yield_ton_ha=float(payload.get("avg_yield_ton_ha") or 0.0),
        )
    except (KeyError, TypeError, ValueError):
        return None


@router.post(
    "/knowledge/search",
    response_model=KnowledgeSearchResponse,
    summary="Hybrid (dense + sparse) semantic search over yield passages",
    description=(
        "Returns the top-N most relevant yield passages for a natural-language "
        "query. **Pure retrieval** — this endpoint does not summarize, list, or "
        "answer in prose. Callers (UI or LLM agent) decide what to do with the hits.\n\n"
        "**How it works**\n\n"
        "- Each yield row is indexed as a textified passage in `prism_yield_knowledge`.\n"
        "- The query is embedded with both **dense** (`BAAI/bge-small-en-v1.5`) and "
        "**sparse** (`Qdrant/bm25`) models.\n"
        "- Results are fused via Reciprocal Rank Fusion (RRF) on Qdrant's side.\n"
        "- Optional `filters` are applied **before** scoring (cheap pre-filter).\n"
        "- `min_score` drops weak matches client-side.\n\n"
        "**Request body**\n\n"
        "- `query` (required, 1–2000 chars) — natural-language question or keyword string.\n"
        "- `limit` (default 10, max 100) — top-K results.\n"
        "- `filters` (optional) — scope retrieval to a region / province / year range / semester.\n"
        "- `min_score` (default 0.0) — minimum fused score (0.0 – 1.0).\n\n"
        "**Examples**\n\n"
        "```bash\n"
        "# Free-text\n"
        "curl -X POST http://localhost:8000/v1/knowledge/search \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        "  -d '{\"query\":\"Bangued Abra 2018 first sem\",\"limit\":5}'\n\n"
        "# Filtered to one region/year range\n"
        "curl -X POST http://localhost:8000/v1/knowledge/search \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        "  -d '{\"query\":\"rice yield trends\",\"limit\":10,\\\n"
        "       \"filters\":{\"region\":\"CAR\",\"year_min\":2020,\"year_max\":2023}}'\n"
        "```\n\n"
        "**Other endpoints to consider**\n\n"
        "- Need totals/averages → `GET /v1/yield/summary` (deterministic math).\n"
        "- Need exact rows by ID-able filters → `GET /v1/yield`.\n\n"
        "**Auth**: public tier. Rate-limited 30/min per key."
    ),
)
@limiter.limit(rate_limit_search)
def knowledge_search(
    request: Request,
    body: KnowledgeSearchRequest,
    _scope: object = Depends(require_public),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
) -> KnowledgeSearchResponse:
    del request
    flt = filter_from_knowledge_filters(body.filters)
    started = time.perf_counter()
    records = store.hybrid_search(
        query_text=body.query,
        flt=flt,
        limit=body.limit,
        min_score=body.min_score,
    )
    took_ms = round((time.perf_counter() - started) * 1000, 2)

    hits = [hit for hit in (_hit_record_to_schema(r) for r in records) if hit is not None]
    return KnowledgeSearchResponse(
        query=body.query,
        filters=body.filters,
        hits=hits,
        took_ms=took_ms,
    )
