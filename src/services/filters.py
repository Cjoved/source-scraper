"""Validation + construction of `YieldFilter` from HTTP request parameters.

Keeping filter construction in `services/` lets both route handlers and the
indexer reuse it without depending on the API layer's Pydantic models.
"""

from __future__ import annotations

from src.api.errors import ApiError, ErrorCode
from src.api.schemas import KnowledgeFilters, SemesterCode
from src.storage.qdrant_store import YieldFilter


def build_yield_filter(
    *,
    year: int | None = None,
    semester: SemesterCode | None = None,
    region: str | None = None,
    province: str | None = None,
    municipality: str | None = None,
    min_yield: float | None = None,
    max_yield: float | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
) -> YieldFilter:
    if year_min is not None and year_max is not None and year_min > year_max:
        raise ApiError(
            ErrorCode.INVALID_FILTER,
            "year_min must be <= year_max",
            status_code=400,
            details={"year_min": year_min, "year_max": year_max},
        )
    if min_yield is not None and max_yield is not None and min_yield > max_yield:
        raise ApiError(
            ErrorCode.INVALID_FILTER,
            "min_yield must be <= max_yield",
            status_code=400,
            details={"min_yield": min_yield, "max_yield": max_yield},
        )
    return YieldFilter(
        year=year,
        year_min=year_min,
        year_max=year_max,
        semester=semester,
        region=region.strip() if region else None,
        province=province.strip() if province else None,
        municipality=municipality.strip() if municipality else None,
        min_yield=min_yield,
        max_yield=max_yield,
    )


def filter_from_knowledge_filters(filters: KnowledgeFilters | None) -> YieldFilter:
    if filters is None:
        return YieldFilter()
    return build_yield_filter(
        region=filters.region,
        province=filters.province,
        municipality=filters.municipality,
        year_min=filters.year_min,
        year_max=filters.year_max,
        semester=filters.semester,
    )
