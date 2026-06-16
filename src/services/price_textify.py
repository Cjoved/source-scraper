"""Pure row-to-passage textifier for OpenSTAT farmgate price knowledge collection.

One natural-language sentence per row (same style as yield ``textify`` and
``openstat_cpt.row_to_sentence``), plus a short source suffix for BM25 tokens.
"""

from __future__ import annotations

from typing import Any


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def row_to_passage(row: dict[str, Any]) -> str:
    """Render a normalized OpenSTAT price row as a single searchable passage."""
    month = _safe_str(row.get("month")) or "an unknown month"
    year = row.get("year")
    year_text = str(int(year)) if year is not None else "an unknown year"
    geolocation = _safe_str(row.get("geolocation")) or "an unknown location"
    commodity = _safe_str(row.get("commodity")) or _safe_str(row.get("commodity_type")) or "commodity"
    commodity_type = _safe_str(row.get("commodity_type"))
    price = row.get("price_php_per_kg")

    source_bits = ["PSA OpenSTAT"]
    if commodity_type:
        source_bits.append(commodity_type)
    source_suffix = f" (Source: {', '.join(source_bits)})"

    if price is None:
        return (
            f"In {month} {year_text}, the farmgate price of {commodity} "
            f"in {geolocation} had no recorded data.{source_suffix}"
        )

    try:
        price_value = float(price)
    except (TypeError, ValueError):
        return (
            f"In {month} {year_text}, the farmgate price of {commodity} "
            f"in {geolocation} had no recorded data.{source_suffix}"
        )

    return (
        f"In {month} {year_text}, the farmgate price of {commodity} "
        f"in {geolocation} was ₱{price_value:.2f} per kilogram.{source_suffix}"
    )
