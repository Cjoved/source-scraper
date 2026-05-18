"""Yield data routes: list, metadata, summary, and bulk export.

All four routes share the same filter shape, normalized via
:func:`src.services.filters.build_yield_filter`. The summary route uses an
LRU cache keyed by the source CSV mtime so identical scopes return instantly
while still invalidating after a re-index.
"""

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
    get_csv_source_path,
    get_metadata_cache,
    get_qdrant_store,
)
from src.api.errors import ApiError, ErrorCode
from src.api.metadata_cache import MetadataCache
from src.api.rate_limit import limiter
from src.api.schemas import (
    ExportFormat,
    SemesterCode,
    SemesterMetadata,
    SummaryScope,
    YieldListResponse,
    YieldMetadataResponse,
    YieldRow,
    YieldSummaryResponse,
)
from src.api.settings import Settings, get_settings
from src.services.aggregation import aggregate_rows
from src.services.filters import build_yield_filter
from src.storage.qdrant_store import QdrantStoreProtocol, YieldFilter

router = APIRouter(tags=["yield"])

_EXPORT_FIELDNAMES: tuple[str, ...] = (
    "year",
    "semester_code",
    "semester_label",
    "region",
    "province",
    "municipality",
    "avg_yield_ton_ha",
    "scraped_at",
)


def _row_to_schema(row: dict[str, object]) -> YieldRow:
    try:
        return YieldRow.model_validate(row)
    except Exception as exc:
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            "Stored row does not match schema",
            status_code=500,
            details={"reason": exc.__class__.__name__},
        ) from exc


@router.get(
    "/yield",
    response_model=YieldListResponse,
    summary="List yield rows (paginated, filterable)",
    description=(
        "Return individual yield rows from the structured Qdrant collection. "
        "Use this for UI tables, dashboard browsing, and slicing data into "
        "filtered views.\n\n"
        "**Filters** (all optional, AND-combined)\n\n"
        "- `year` — exact year (e.g. `2020`).\n"
        "- `semester` — `1` (1st sem) or `2` (2nd sem).\n"
        "- `region`, `province`, `municipality` — exact match (case-sensitive).\n"
        "- `min_yield`, `max_yield` — clamp on `avg_yield_ton_ha`.\n\n"
        "**Pagination**\n\n"
        "- `limit` (default `100`, max `1000`).\n"
        "- `offset` (default `0`).\n"
        "- The response includes `next_offset` (or `null` if no more pages).\n\n"
        "**Examples**\n\n"
        "```bash\n"
        "curl 'http://localhost:8000/v1/yield?region=CAR&year=2020&limit=10'\n"
        "curl 'http://localhost:8000/v1/yield?province=Abra&min_yield=3.0'\n"
        "```\n\n"
        "**Other endpoints to consider**\n\n"
        "- Need totals/averages instead of rows → `GET /v1/yield/summary`.\n"
        "- Need a full dump → `GET /v1/yield/export`.\n"
        "- Free-text question → `POST /v1/knowledge/search`.\n\n"
        "**Auth**: public tier."
    ),
)
@limiter.limit("120/minute")
def list_yield_rows(
    request: Request,
    year: int | None = Query(default=None, ge=1900, le=2100, description="Exact year filter."),
    semester: SemesterCode | None = Query(default=None, description="1 = 1st sem, 2 = 2nd sem."),
    region: str | None = Query(default=None, max_length=64, description="Exact region name (e.g. `CAR`)."),
    province: str | None = Query(default=None, max_length=64, description="Exact province name (e.g. `Abra`)."),
    municipality: str | None = Query(default=None, max_length=64, description="Exact municipality name."),
    min_yield: float | None = Query(default=None, ge=0, description="Lower bound on avg yield (ton/ha)."),
    max_yield: float | None = Query(default=None, ge=0, description="Upper bound on avg yield (ton/ha)."),
    limit: int = Query(default=100, ge=1, le=1000, description="Page size (1–1000)."),
    offset: int = Query(default=0, ge=0, description="Number of rows to skip."),
    _scope: object = Depends(require_public),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
) -> YieldListResponse:
    del request
    flt = build_yield_filter(
        year=year,
        semester=semester,
        region=region,
        province=province,
        municipality=municipality,
        min_yield=min_yield,
        max_yield=max_yield,
    )
    rows, next_offset = store.scroll_yield_rows(flt, limit=limit, offset=offset)
    items = [_row_to_schema(r) for r in rows]
    total = store.count_yield_rows(flt)
    return YieldListResponse(items=items, total=total, next_offset=next_offset)


@router.get(
    "/yield/metadata",
    response_model=YieldMetadataResponse,
    summary="Distinct filter values (years, semesters, regions, provinces, municipalities)",
    description=(
        "Returns the distinct values needed to populate filter widgets on the "
        "frontend (dropdowns, autocomplete). Served from an in-memory cache that "
        "is built at startup and rebuilt by `POST /v1/index/refresh-metadata`.\n\n"
        "**Use cases**\n\n"
        "- Build the Region → Province → Municipality cascading dropdowns.\n"
        "- Determine valid year range for date pickers.\n\n"
        "**Cascading keys**\n\n"
        "- `provinces_by_region[region]` — province list for the selected region.\n"
        "- `municipalities_by_region_province[region][province]` — municipality list.\n\n"
        "**Note**: empty arrays mean Qdrant has no data yet — run the indexer first.\n\n"
        "**Auth**: public tier."
    ),
)
@limiter.limit("120/minute")
def get_yield_metadata(
    request: Request,
    _scope: object = Depends(require_public),
    cache: MetadataCache = Depends(get_metadata_cache),
) -> YieldMetadataResponse:
    del request
    snapshot = cache.get()
    semesters = list(snapshot.semesters) or [
        SemesterMetadata(code=SemesterCode.FIRST, label=""),
        SemesterMetadata(code=SemesterCode.SECOND, label=""),
    ]
    return YieldMetadataResponse(
        years=list(snapshot.years),
        semesters=semesters,
        regions=list(snapshot.regions),
        provinces_by_region={r: list(p) for r, p in snapshot.provinces_by_region.items()},
        municipalities_by_region_province={
            region: {province: list(municipalities) for province, municipalities in provinces.items()}
            for region, provinces in snapshot.municipalities_by_region_province.items()
        },
    )


def _summary_cache_key(
    flt: YieldFilter,
    mtime: float,
) -> tuple[float, tuple[object, ...]]:
    return (
        mtime,
        (
            flt.year,
            flt.year_min,
            flt.year_max,
            int(flt.semester) if flt.semester is not None else None,
            flt.region,
            flt.province,
            flt.municipality,
            flt.min_yield,
            flt.max_yield,
        ),
    )


@lru_cache(maxsize=256)
def _cached_summary(
    cache_key: tuple[float, tuple[object, ...]],
    flt_repr: str,
    rows_tuple: tuple[tuple[tuple[str, object], ...], ...],
    scope_json: str,
) -> YieldSummaryResponse:
    del cache_key, flt_repr
    scope = SummaryScope.model_validate_json(scope_json)
    rows = [dict(items) for items in rows_tuple]
    return aggregate_rows(rows, scope=scope)


@router.get(
    "/yield/summary",
    response_model=YieldSummaryResponse,
    summary="Deterministic aggregation (avg, min, max, by-year, by-semester)",
    description=(
        "Returns **exact math** over the yield rows in scope. Use this when the "
        "user wants a number: average yield for a province, year-over-year trend, "
        "min/max yields, etc. This endpoint never approximates and never embeds.\n\n"
        "**Scope params** (all optional, AND-combined)\n\n"
        "- `region`, `province`, `municipality` — narrow the geographic scope.\n"
        "- `year_min`, `year_max` — inclusive year range.\n"
        "- `semester` — `1` or `2`.\n\n"
        "**Response shape**\n\n"
        "- `overall`: average, row count, municipality count, min/max with locators.\n"
        "- `by_year`: per-year averages and row counts.\n"
        "- `by_semester`: per (year, semester) averages and row counts.\n\n"
        "**Example**\n\n"
        "```bash\n"
        "curl 'http://localhost:8000/v1/yield/summary?province=Abra&year_min=2019&year_max=2025'\n"
        "```\n\n"
        "**Performance**: results are cached using the source CSV mtime as key, "
        "so identical scopes return in sub-millisecond after the first call.\n\n"
        "**Auth**: public tier."
    ),
)
@limiter.limit("120/minute")
def get_yield_summary(
    request: Request,
    region: str | None = Query(default=None, description="Narrow scope to a single region."),
    province: str | None = Query(default=None, description="Narrow scope to a single province."),
    municipality: str | None = Query(default=None, description="Narrow scope to a single municipality."),
    year_min: int | None = Query(default=None, ge=1900, le=2100, description="Inclusive lower year bound."),
    year_max: int | None = Query(default=None, ge=1900, le=2100, description="Inclusive upper year bound."),
    semester: SemesterCode | None = Query(default=None, description="1 = 1st sem, 2 = 2nd sem."),
    _scope: object = Depends(require_public),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
    csv_path: Path = Depends(get_csv_source_path),
) -> YieldSummaryResponse:
    del request
    flt = build_yield_filter(
        region=region,
        province=province,
        municipality=municipality,
        year_min=year_min,
        year_max=year_max,
        semester=semester,
    )
    scope = SummaryScope(
        region=region,
        province=province,
        municipality=municipality,
        year_min=year_min,
        year_max=year_max,
        semester=semester,
    )
    rows = list(store.iter_yield_rows(flt))
    if not rows:
        return aggregate_rows([], scope=scope)

    mtime = csv_path.stat().st_mtime if csv_path.is_file() else 0.0
    rows_tuple = tuple(tuple(sorted(r.items())) for r in rows)
    return _cached_summary(
        _summary_cache_key(flt, mtime),
        repr(flt),
        rows_tuple,
        scope.model_dump_json(),
    )


def _export_filename(flt: YieldFilter, fmt: ExportFormat) -> str:
    parts = ["prism_yield"]
    if flt.region:
        parts.append(flt.region.replace(" ", "_"))
    if flt.province:
        parts.append(flt.province.replace(" ", "_"))
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
    "/yield/export",
    summary="Bulk export of yield rows (NDJSON or CSV stream)",
    description=(
        "Stream the full dataset (or a filtered slice) row-by-row, low memory on "
        "both sides. **Two formats** via the `format` query parameter:\n\n"
        "- `ndjson` (default) — one JSON object per line, `Content-Type: application/x-ndjson`.\n"
        "- `csv` — comma-separated values with snake_case headers, `Content-Type: text/csv`.\n\n"
        "Same filters as `GET /v1/yield` are supported.\n\n"
        "**Examples**\n\n"
        "```bash\n"
        "# Full NDJSON dump\n"
        "curl -H 'X-API-Key: $ADMIN_KEY' \\\n"
        "  http://localhost:8000/v1/yield/export > all_yield.ndjson\n\n"
        "# CSV slice for Region III, 2023\n"
        "curl -H 'X-API-Key: $ADMIN_KEY' \\\n"
        "  'http://localhost:8000/v1/yield/export?format=csv&region=Region+III&year=2023' \\\n"
        "  > region3_2023.csv\n"
        "```\n\n"
        "**Protections**\n\n"
        "- Server-side `EXPORT_MAX_ROWS` cap (default 100,000).\n"
        "- Admin scope required.\n"
        "- Rate-limited 5/min per key.\n\n"
        "**Auth**: admin tier (`X-API-Key` matching `API_KEYS_ADMIN`)."
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Streamed body in the requested format.",
            "content": {
                "application/x-ndjson": {
                    "example": (
                        '{"year":2018,"region":"CAR","province":"Abra","municipality":"Bangued",'
                        '"avg_yield_ton_ha":3.03}\n'
                        '{"year":2018,"region":"CAR","province":"Abra","municipality":"Bucay",'
                        '"avg_yield_ton_ha":3.51}\n'
                    )
                },
                "text/csv": {
                    "example": (
                        "year,semester_code,semester_label,region,province,municipality,"
                        "avg_yield_ton_ha,scraped_at\n"
                        "2018,1,1st Semester (Sept16-Mar15),CAR,Abra,Bangued,3.03,"
                        "2026-05-08T11:04:25\n"
                    )
                },
            },
        }
    },
)
@limiter.limit("5/minute")
def export_yield_rows(
    request: Request,
    format: ExportFormat = Query(
        default=ExportFormat.NDJSON,
        alias="format",
        description="`ndjson` (default) or `csv`.",
    ),
    year: int | None = Query(default=None, ge=1900, le=2100),
    semester: SemesterCode | None = Query(default=None),
    region: str | None = Query(default=None, max_length=64),
    province: str | None = Query(default=None, max_length=64),
    municipality: str | None = Query(default=None, max_length=64),
    min_yield: float | None = Query(default=None, ge=0),
    max_yield: float | None = Query(default=None, ge=0),
    _scope: object = Depends(require_admin),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    del request
    flt = build_yield_filter(
        year=year,
        semester=semester,
        region=region,
        province=province,
        municipality=municipality,
        min_yield=min_yield,
        max_yield=max_yield,
    )
    iterator = store.iter_yield_rows(flt, max_rows=settings.export_max_rows)
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
