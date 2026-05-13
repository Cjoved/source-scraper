"""Pure row-to-passage textifier for the hybrid knowledge collection.

The goal is a single natural-language sentence per CSV row that contains every
filterable token in plain form (year, semester, region, province, municipality,
yield, scrape date). Sparse models like BM25 benefit from exact tokens; dense
models benefit from the surrounding natural-language context.
"""

from __future__ import annotations

from typing import Any


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _date_only(scraped_at: str) -> str:
    if not scraped_at:
        return ""
    return scraped_at.split(" ", 1)[0].split("T", 1)[0]


def row_to_passage(row: dict[str, Any]) -> str:
    """Render a normalized yield row as a natural-language passage."""
    year = _safe_str(row.get("year"))
    semester_label = _safe_str(row.get("semester_label"))
    region = _safe_str(row.get("region"))
    province = _safe_str(row.get("province"))
    municipality = _safe_str(row.get("municipality")) or "(unknown municipality)"
    avg_yield = row.get("avg_yield_ton_ha")
    scraped_at = _safe_str(row.get("scraped_at"))
    date_part = _date_only(scraped_at)

    try:
        avg_yield_str = f"{float(avg_yield):.2f}"
    except (TypeError, ValueError):
        avg_yield_str = _safe_str(avg_yield) or "0.00"

    location_bits = [municipality]
    if province:
        location_bits.append(f"in {province}")
    if region:
        location_bits.append(f"{region}")
    location = ", ".join(location_bits)

    sem_part = f" {semester_label}" if semester_label else ""
    scrape_part = f" (Source: PRiSM, scraped {date_part})" if date_part else " (Source: PRiSM)"

    return (
        f"In {year}{sem_part}, the municipality of {location} recorded "
        f"an average rice yield of {avg_yield_str} ton/ha.{scrape_part}"
    )
