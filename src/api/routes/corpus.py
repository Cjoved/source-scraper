"""Unified RAG corpus search route (P3.8d)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_public
from src.api.deps import get_qdrant_store
from src.api.rate_limit import limiter
from src.api.schemas import (
    CorpusHit,
    CorpusSearchRequest,
    CorpusSearchResponse,
)
from src.storage.qdrant_store import CorpusFilter, KnowledgeHitRecord, QdrantStoreProtocol

router = APIRouter(tags=["corpus"])


def _hit_record_to_schema(record: KnowledgeHitRecord) -> CorpusHit | None:
    payload = record.payload
    try:
        return CorpusHit(
            score=record.score,
            text=str(payload.get("text") or ""),
            source_id=str(payload["source_id"]),
            doc_id=str(payload["doc_id"]),
            url=str(payload["url"]) if payload.get("url") else None,
            title=str(payload["title"]) if payload.get("title") else None,
            filename=str(payload["filename"]) if payload.get("filename") else None,
            page=int(payload["page"]) if payload.get("page") is not None else None,
        )
    except (KeyError, TypeError, ValueError):
        return None


@router.post(
    "/corpus/search",
    response_model=CorpusSearchResponse,
    summary="Hybrid semantic search over unified agri corpus",
    description=(
        "Returns the top-N most relevant passages from the unified "
        "`agri_corpus_rag` collection (PhilRice, News, PinoyRice, IRRI, "
        "PRiSM browser chunks). **Pure retrieval** — no LLM generation. "
        "PSA OpenSTAT farmgate prices (`openstat_table.csv`) and yield CSV "
        "data are not in this collection — use structured endpoints when available.\n\n"
        "**Auth**: public tier. Rate-limited 30/min per key."
    ),
)
@limiter.limit("30/minute")
def corpus_search(
    request: Request,
    body: CorpusSearchRequest,
    _scope: object = Depends(require_public),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
) -> CorpusSearchResponse:
    del request
    source_filter = tuple(body.source_ids) if body.source_ids else None
    flt = CorpusFilter(source_ids=source_filter)
    started = time.perf_counter()
    records = store.search_corpus(
        query_text=body.query,
        flt=flt,
        limit=body.limit,
        min_score=body.min_score,
    )
    took_ms = round((time.perf_counter() - started) * 1000, 2)

    hits = [hit for hit in (_hit_record_to_schema(r) for r in records) if hit is not None]
    return CorpusSearchResponse(
        query=body.query,
        limit=body.limit,
        source_ids=body.source_ids,
        hits=hits,
        took_ms=took_ms,
    )
