"""Admin routes: index status and metadata cache refresh."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_admin
from src.api.deps import (
    get_csv_source_path,
    get_metadata_cache,
    get_openstat_csv_path,
    get_qdrant_store,
)
from src.api.metadata_cache import MetadataCache, build_snapshot_from_rows
from src.api.limit_config import rate_limit_read, rate_limit_search
from src.api.rate_limit import limiter
from src.api.schemas import (
    CollectionStatus,
    IndexStatusResponse,
    RefreshMetadataResponse,
)
from src.storage.qdrant_store import QdrantStoreProtocol, YieldFilter

router = APIRouter(tags=["admin"])


def _format_mtime(path: Path) -> str | None:
    if not path.is_file():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")


def _count_csv_rows(path: Path) -> int | None:
    if not path.is_file():
        return None
    count = 0
    with path.open("r", encoding="utf-8") as fh:
        for _ in fh:
            count += 1
    return max(count - 1, 0)


@router.get(
    "/index/status",
    response_model=IndexStatusResponse,
    summary="Index counts, schema version, and source CSV freshness",
    description=(
        "Operator-focused view of the indexing state. Returns:\n\n"
        "- Per-collection point counts (yield, OpenSTAT prices, corpus RAG).\n"
        "- Configured vector names per collection (helps spot misconfigurations).\n"
        "- The current `schema_version` from settings.\n"
        "- Source CSV path, row count, and last modification timestamp.\n\n"
        "**How to interpret**\n\n"
        "- If `source_mtime` is newer than your last indexing run, re-index.\n"
        "- If `points` is `0`, the indexer has not run successfully yet.\n\n"
        "**Auth**: admin tier."
    ),
)
@limiter.limit(rate_limit_read)
def index_status(
    request: Request,
    _scope: object = Depends(require_admin),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
    csv_path: Path = Depends(get_csv_source_path),
    openstat_csv_path: Path = Depends(get_openstat_csv_path),
) -> IndexStatusResponse:
    del request
    collections = [
        CollectionStatus(
            name=stats.name,
            points=stats.points,
            schema_version=stats.schema_version,
            vectors=stats.vectors,
        )
        for stats in store.collection_stats()
    ]
    return IndexStatusResponse(
        collections=collections,
        source_file=str(csv_path),
        source_rows=_count_csv_rows(csv_path),
        source_mtime=_format_mtime(csv_path),
        openstat_source_file=str(openstat_csv_path),
        openstat_source_rows=_count_csv_rows(openstat_csv_path),
        openstat_source_mtime=_format_mtime(openstat_csv_path),
    )


@router.post(
    "/index/refresh-metadata",
    response_model=RefreshMetadataResponse,
    summary="Rebuild the in-memory metadata cache (no server restart needed)",
    description=(
        "Scans the structured Qdrant collection and rebuilds the in-memory snapshot "
        "used by `GET /v1/yield/metadata`. The new snapshot is swapped in atomically; "
        "in-flight requests continue to use the previous snapshot.\n\n"
        "**When to call this**\n\n"
        "- Right after a successful re-index (new provinces / years may have appeared).\n"
        "- When `/v1/yield/metadata` returns empty arrays but you know Qdrant has data.\n\n"
        "**Returns** counts of the rebuilt cache plus elapsed time in ms.\n\n"
        "**Auth**: admin tier. Rate-limited 30/min per key."
    ),
)
@limiter.limit(rate_limit_search)
def refresh_metadata(
    request: Request,
    _scope: object = Depends(require_admin),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
    cache: MetadataCache = Depends(get_metadata_cache),
) -> RefreshMetadataResponse:
    del request
    started = time.perf_counter()
    rows = list(store.iter_yield_rows(YieldFilter()))
    snapshot = build_snapshot_from_rows(rows)
    cache.set(snapshot)
    took_ms = round((time.perf_counter() - started) * 1000, 2)
    return RefreshMetadataResponse(
        refreshed=True,
        regions_count=snapshot.regions_count,
        provinces_count=snapshot.provinces_count,
        municipalities_count=snapshot.municipalities_count,
        years_count=snapshot.years_count,
        took_ms=took_ms,
    )
