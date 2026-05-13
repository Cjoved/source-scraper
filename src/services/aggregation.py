"""Pure aggregation over normalized yield rows.

This module is framework-free. Routes call into it with materialized lists of
rows (or a generator) and receive a fully-typed summary back.
"""

from __future__ import annotations

from collections.abc import Iterable

from src.api.schemas import (
    SemesterCode,
    SummaryByYear,
    SummaryBySemester,
    SummaryOverall,
    SummaryScope,
    YieldExtremum,
    YieldSummaryResponse,
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


def aggregate_rows(rows: Iterable[dict[str, object]], scope: SummaryScope) -> YieldSummaryResponse:
    """Compute overall + per-year + per-semester aggregations.

    Rows are expected to use the normalized payload shape produced by the
    indexer (`year`, `semester_code`, `region`, `province`, `municipality`,
    `avg_yield_ton_ha`). Missing/invalid rows are skipped defensively.
    """
    total_sum = 0.0
    row_count = 0
    municipalities: set[tuple[str, str]] = set()

    min_extremum: YieldExtremum | None = None
    max_extremum: YieldExtremum | None = None

    by_year_sum: dict[int, float] = {}
    by_year_count: dict[int, int] = {}

    by_sem_sum: dict[tuple[int, int], float] = {}
    by_sem_count: dict[tuple[int, int], int] = {}

    for raw in rows:
        year = _coerce_int(raw.get("year"))
        sem = _coerce_int(raw.get("semester_code"))
        yield_val = _coerce_float(raw.get("avg_yield_ton_ha"))
        if year is None or sem is None or yield_val is None or sem not in (1, 2):
            continue

        row_count += 1
        total_sum += yield_val

        province = str(raw.get("province") or "")
        municipality = str(raw.get("municipality") or "")
        if municipality:
            municipalities.add((province, municipality))

        by_year_sum[year] = by_year_sum.get(year, 0.0) + yield_val
        by_year_count[year] = by_year_count.get(year, 0) + 1

        sem_key = (year, sem)
        by_sem_sum[sem_key] = by_sem_sum.get(sem_key, 0.0) + yield_val
        by_sem_count[sem_key] = by_sem_count.get(sem_key, 0) + 1

        extremum = YieldExtremum(
            value=yield_val,
            year=year,
            semester_code=SemesterCode(sem),
            region=str(raw.get("region") or ""),
            province=province,
            municipality=municipality,
        )
        if min_extremum is None or yield_val < min_extremum.value:
            min_extremum = extremum
        if max_extremum is None or yield_val > max_extremum.value:
            max_extremum = extremum

    overall = SummaryOverall(
        avg_yield_ton_ha=round(total_sum / row_count, 4) if row_count else 0.0,
        min=min_extremum,
        max=max_extremum,
        row_count=row_count,
        municipality_count=len(municipalities),
    )

    by_year = [
        SummaryByYear(
            year=year,
            avg_yield_ton_ha=round(by_year_sum[year] / by_year_count[year], 4),
            row_count=by_year_count[year],
        )
        for year in sorted(by_year_sum)
    ]

    by_semester = [
        SummaryBySemester(
            year=year,
            semester_code=SemesterCode(sem),
            avg_yield_ton_ha=round(by_sem_sum[(year, sem)] / by_sem_count[(year, sem)], 4),
            row_count=by_sem_count[(year, sem)],
        )
        for year, sem in sorted(by_sem_sum)
    ]

    return YieldSummaryResponse(
        scope=scope,
        overall=overall,
        by_year=by_year,
        by_semester=by_semester,
    )
