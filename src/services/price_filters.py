"""Validation + construction of ``PriceFilter`` from HTTP request parameters."""

from __future__ import annotations

from src.api.errors import ApiError, ErrorCode
from src.api.schemas import PriceFilters
from src.storage.qdrant_store import PriceFilter


def build_price_filter(
    *,
    geolocation: str | None = None,
    commodity_type: str | None = None,
    commodity: str | None = None,
    year: int | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    month: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
) -> PriceFilter:
    if year_min is not None and year_max is not None and year_min > year_max:
        raise ApiError(
            ErrorCode.INVALID_FILTER,
            "year_min must be <= year_max",
            status_code=400,
            details={"year_min": year_min, "year_max": year_max},
        )
    if min_price is not None and max_price is not None and min_price > max_price:
        raise ApiError(
            ErrorCode.INVALID_FILTER,
            "min_price must be <= max_price",
            status_code=400,
            details={"min_price": min_price, "max_price": max_price},
        )
    return PriceFilter(
        geolocation=geolocation.strip() if geolocation else None,
        commodity_type=commodity_type.strip() if commodity_type else None,
        commodity=commodity.strip() if commodity else None,
        year=year,
        year_min=year_min,
        year_max=year_max,
        month=month.strip() if month else None,
        min_price=min_price,
        max_price=max_price,
    )


def filter_from_price_filters(filters: PriceFilters | None) -> PriceFilter:
    if filters is None:
        return PriceFilter()
    return build_price_filter(
        geolocation=filters.geolocation,
        commodity_type=filters.commodity_type,
        commodity=filters.commodity,
        year_min=filters.year_min,
        year_max=filters.year_max,
        month=filters.month,
    )
