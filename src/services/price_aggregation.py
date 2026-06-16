"""Pure aggregation over normalized OpenSTAT price rows."""

from __future__ import annotations

from collections.abc import Iterable

from src.api.schemas import (
    PriceExtremum,
    PriceSummaryByMonth,
    PriceSummaryByYear,
    PriceSummaryOverall,
    PriceSummaryResponse,
    PriceSummaryScope,
)


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _coerce_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def aggregate_price_rows(
    rows: Iterable[dict[str, object]],
    scope: PriceSummaryScope,
) -> PriceSummaryResponse:
    """Compute overall + per-year + per-month price aggregations."""
    total_sum = 0.0
    row_count = 0
    priced_rows = 0

    min_extremum: PriceExtremum | None = None
    max_extremum: PriceExtremum | None = None

    by_year_sum: dict[int, float] = {}
    by_year_count: dict[int, int] = {}

    by_month_sum: dict[tuple[int, str], float] = {}
    by_month_count: dict[tuple[int, str], int] = {}

    for raw in rows:
        year = _coerce_int(raw.get("year"))
        month = str(raw.get("month") or "").strip()
        price_val = _coerce_float(raw.get("price_php_per_kg"))
        if year is None or not month:
            continue

        row_count += 1
        if price_val is None:
            continue

        priced_rows += 1
        total_sum += price_val

        by_year_sum[year] = by_year_sum.get(year, 0.0) + price_val
        by_year_count[year] = by_year_count.get(year, 0) + 1

        month_key = (year, month)
        by_month_sum[month_key] = by_month_sum.get(month_key, 0.0) + price_val
        by_month_count[month_key] = by_month_count.get(month_key, 0) + 1

        extremum = PriceExtremum(
            value=price_val,
            year=year,
            month=month,
            geolocation=str(raw.get("geolocation") or ""),
            commodity=str(raw.get("commodity") or ""),
        )
        if min_extremum is None or price_val < min_extremum.value:
            min_extremum = extremum
        if max_extremum is None or price_val > max_extremum.value:
            max_extremum = extremum

    overall = PriceSummaryOverall(
        avg_price_php_per_kg=round(total_sum / priced_rows, 2) if priced_rows else 0.0,
        min=min_extremum,
        max=max_extremum,
        row_count=row_count,
        priced_row_count=priced_rows,
    )

    by_year = [
        PriceSummaryByYear(
            year=year,
            avg_price_php_per_kg=round(by_year_sum[year] / by_year_count[year], 2),
            row_count=by_year_count[year],
        )
        for year in sorted(by_year_sum)
    ]

    by_month = [
        PriceSummaryByMonth(
            year=year,
            month=month,
            avg_price_php_per_kg=round(by_month_sum[(year, month)] / by_month_count[(year, month)], 2),
            row_count=by_month_count[(year, month)],
        )
        for year, month in sorted(by_month_sum, key=lambda k: (k[0], k[1]))
    ]

    return PriceSummaryResponse(
        scope=scope,
        overall=overall,
        by_year=by_year,
        by_month=by_month,
    )
