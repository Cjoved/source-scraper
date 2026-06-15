"""OpenSTAT farmgate price routes: list, metadata, summary, export, and search."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from src.api.auth import require_admin, require_public
from src.api.deps import (
    get_openstat_csv_path,
    get_price_metadata_cache,
    get_qdrant_store,
)
from src.api.errors import ApiError, ErrorCode
from src.api.price_metadata_cache import PriceMetadataCache
from src.api.rate_limit import limiter
from src.api.schemas import (
    ExportFormat,
    PriceFilters,
    PriceHit,
    PriceListResponse,
    PriceMetadataResponse,
    PriceRow,
    PriceSearchRequest,
    PriceSearchResponse,
    PriceSummaryResponse,
    PriceSummaryScope,
    RefreshPriceMetadataResponse,
)
from src.api.settings import Settings, get_settings
from src.services.price_aggregation import aggregate_price_rows
from src.services.price_filters import build_price_filter, filter_from_price_filters
from src.storage.qdrant_store import KnowledgeHitRecord, PriceFilter, QdrantStoreProtocol

router = APIRouter(tags=["prices"])

_EXPORT_FIELDNAMES: tuple[str, ...] = (
    "geolocation",
    "commodity_type",
    "commodity",
    "year",
    "month",
    "price_php_per_kg",
    "source",
)


def _row_to_schema(row: dict[str, object]) -> PriceRow:
    try:
        return PriceRow.model_validate(row)
    except Exception as exc:
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            "Stored row does not match schema",
            status_code=500,
            details={"reason": exc.__class__.__name__},
        ) from exc


def _hit_record_to_schema(record: KnowledgeHitRecord) -> PriceHit | None:
    payload = record.payload
    try:
        return PriceHit(
            score=record.score,
            text=str(payload.get("text") or ""),
            geolocation=str(payload["geolocation"]),
            commodity_type=str(payload.get("commodity_type") or ""),
            commodity=str(payload["commodity"]),
            year=int(payload["year"]),
            month=str(payload["month"]),
            price_php_per_kg=(
                float(payload["price_php_per_kg"])
                if payload.get("price_php_per_kg") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


@router.get(
    "/prices",
    response_model=PriceListResponse,
    summary="List PSA farmgate price rows (paginated, filterable)",
)
@limiter.limit("120/minute")
def list_price_rows(
    request: Request,
    geolocation: str | None = Query(default=None, max_length=128),
    commodity_type: str | None = Query(default=None, max_length=64),
    commodity: str | None = Query(default=None, max_length=128),
    year: int | None = Query(default=None, ge=1900, le=2100),
    year_min: int | None = Query(default=None, ge=1900, le=2100),
    year_max: int | None = Query(default=None, ge=1900, le=2100),
    month: str | None = Query(default=None, max_length=32),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    _scope: object = Depends(require_public),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
) -> PriceListResponse:
    del request
    flt = build_price_filter(
        geolocation=geolocation,
        commodity_type=commodity_type,
        commodity=commodity,
        year=year,
        year_min=year_min,
        year_max=year_max,
        month=month,
        min_price=min_price,
        max_price=max_price,
    )
    rows, next_offset = store.scroll_price_rows(flt, limit=limit, offset=offset)
    items = [_row_to_schema(r) for r in rows]
    total = store.count_price_rows(flt)
    return PriceListResponse(items=items, total=total, next_offset=next_offset)


@router.get(
    "/prices/metadata",
    response_model=PriceMetadataResponse,
    summary="Distinct filter values for OpenSTAT prices",
)
@limiter.limit("120/minute")
def get_price_metadata(
    request: Request,
    _scope: object = Depends(require_public),
    cache: PriceMetadataCache = Depends(get_price_metadata_cache),
) -> PriceMetadataResponse:
    del request
    snapshot = cache.get()
    return PriceMetadataResponse(
        years=list(snapshot.years),
        months=list(snapshot.months),
        geolocations=list(snapshot.geolocations),
        commodity_types=list(snapshot.commodity_types),
        commodities_by_type={k: list(v) for k, v in snapshot.commodities_by_type.items()},
    )


def _summary_cache_key(flt: PriceFilter, mtime: float) -> tuple[float, tuple[object, ...]]:
    return (
        mtime,
        (
            flt.geolocation,
            flt.commodity_type,
            flt.commodity,
            flt.year,
            flt.year_min,
            flt.year_max,
            flt.month,
            flt.min_price,
            flt.max_price,
        ),
    )


@lru_cache(maxsize=256)
def _cached_price_summary(
    cache_key: tuple[float, tuple[object, ...]],
    flt_repr: str,
    rows_tuple: tuple[tuple[tuple[str, object], ...], ...],
    scope_json: str,
) -> PriceSummaryResponse:
    del cache_key, flt_repr
    scope = PriceSummaryScope.model_validate_json(scope_json)
    rows = [dict(items) for items in rows_tuple]
    return aggregate_price_rows(rows, scope=scope)


@router.get(
    "/prices/summary",
    response_model=PriceSummaryResponse,
    summary="Deterministic PSA farmgate price aggregation",
)
@limiter.limit("120/minute")
def get_price_summary(
    request: Request,
    geolocation: str | None = Query(default=None),
    commodity_type: str | None = Query(default=None),
    commodity: str | None = Query(default=None),
    year_min: int | None = Query(default=None, ge=1900, le=2100),
    year_max: int | None = Query(default=None, ge=1900, le=2100),
    month: str | None = Query(default=None),
    _scope: object = Depends(require_public),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
    csv_path: Path = Depends(get_openstat_csv_path),
) -> PriceSummaryResponse:
    del request
    flt = build_price_filter(
        geolocation=geolocation,
        commodity_type=commodity_type,
        commodity=commodity,
        year_min=year_min,
        year_max=year_max,
        month=month,
    )
    scope = PriceSummaryScope(
        geolocation=geolocation,
        commodity_type=commodity_type,
        commodity=commodity,
        year_min=year_min,
        year_max=year_max,
        month=month,
    )
    rows = list(store.iter_price_rows(flt))
    if not rows:
        return aggregate_price_rows([], scope=scope)

    mtime = csv_path.stat().st_mtime if csv_path.is_file() else 0.0
    rows_tuple = tuple(tuple(sorted(r.items())) for r in rows)
    return _cached_price_summary(
        _summary_cache_key(flt, mtime),
        repr(flt),
        rows_tuple,
        scope.model_dump_json(),
    )


def _export_filename(flt: PriceFilter, fmt: ExportFormat) -> str:
    parts = ["openstat_prices"]
    if flt.geolocation:
        parts.append(flt.geolocation.replace(" ", "_"))
    if flt.commodity:
        parts.append(flt.commodity.replace(" ", "_")[:40])
    if flt.year is not None:
        parts.append(str(flt.year))
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    parts.append(ts)
    return f"{'_'.join(parts)}.{fmt.value}"


def _stream_ndjson(rows: Iterator[dict[str, object]]) -> Iterator[str]:
    for row in rows:
        yield json.dumps(row, ensure_ascii=False) + "\n"


def _stream_csv(rows: Iterator[dict[str, object]]) -> Iterator[str]:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(_EXPORT_FIELDNAMES), extrasaction="ignore")
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in _EXPORT_FIELDNAMES})
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


@router.get(
    "/prices/export",
    summary="Bulk export of OpenSTAT price rows (NDJSON or CSV stream)",
    response_class=StreamingResponse,
)
@limiter.limit("5/minute")
def export_price_rows(
    request: Request,
    format: ExportFormat = Query(default=ExportFormat.NDJSON, alias="format"),
    geolocation: str | None = Query(default=None, max_length=128),
    commodity_type: str | None = Query(default=None, max_length=64),
    commodity: str | None = Query(default=None, max_length=128),
    year: int | None = Query(default=None, ge=1900, le=2100),
    year_min: int | None = Query(default=None, ge=1900, le=2100),
    year_max: int | None = Query(default=None, ge=1900, le=2100),
    month: str | None = Query(default=None, max_length=32),
    min_price: float | None = Query(default=None, ge=0),
    max_price: float | None = Query(default=None, ge=0),
    _scope: object = Depends(require_admin),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    del request
    flt = build_price_filter(
        geolocation=geolocation,
        commodity_type=commodity_type,
        commodity=commodity,
        year=year,
        year_min=year_min,
        year_max=year_max,
        month=month,
        min_price=min_price,
        max_price=max_price,
    )
    iterator = store.iter_price_rows(flt, max_rows=settings.export_max_rows)
    filename = _export_filename(flt, format)
    if format is ExportFormat.NDJSON:
        return StreamingResponse(
            _stream_ndjson(iterator),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return StreamingResponse(
        _stream_csv(iterator),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/prices/search",
    response_model=PriceSearchResponse,
    summary="Hybrid semantic search over PSA farmgate price passages",
)
@limiter.limit("30/minute")
def search_prices(
    request: Request,
    body: PriceSearchRequest,
    _scope: object = Depends(require_public),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
) -> PriceSearchResponse:
    del request
    import time

    flt = filter_from_price_filters(body.filters)
    started = time.perf_counter()
    records = store.search_prices(
        query_text=body.query,
        flt=flt,
        limit=body.limit,
        min_score=body.min_score,
    )
    took_ms = round((time.perf_counter() - started) * 1000, 2)
    hits = [hit for hit in (_hit_record_to_schema(r) for r in records) if hit is not None]
    return PriceSearchResponse(
        query=body.query,
        filters=body.filters,
        hits=hits,
        took_ms=took_ms,
    )


@router.post(
    "/prices/refresh-metadata",
    response_model=RefreshPriceMetadataResponse,
    summary="Rebuild the in-memory OpenSTAT price metadata cache",
)
@limiter.limit("30/minute")
def refresh_price_metadata_route(
    request: Request,
    _scope: object = Depends(require_admin),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
    cache: PriceMetadataCache = Depends(get_price_metadata_cache),
) -> RefreshPriceMetadataResponse:
    del request
    import time

    from src.api.price_metadata_cache import build_price_snapshot_from_rows

    started = time.perf_counter()
    rows = list(store.iter_price_rows(PriceFilter()))
    snapshot = build_price_snapshot_from_rows(rows)
    cache.set(snapshot)
    took_ms = round((time.perf_counter() - started) * 1000, 2)
    return RefreshPriceMetadataResponse(
        refreshed=True,
        years_count=snapshot.years_count,
        geolocations_count=snapshot.geolocations_count,
        commodities_count=snapshot.commodities_count,
        took_ms=took_ms,
    )
