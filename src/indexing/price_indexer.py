"""One-pass OpenSTAT price CSV indexer.

For each CSV row the indexer produces:

- a :class:`StructuredPoint` for ``openstat_price_records`` (payload-only) and
- a :class:`KnowledgePoint` for ``openstat_price_knowledge`` (textified + payload).
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.api.settings import Settings
from src.services.price_textify import row_to_passage
from src.storage.qdrant_store import (
    KnowledgePoint,
    QdrantStoreProtocol,
    StructuredPoint,
    build_price_point_id,
)

_ANNUAL_MONTHS = {"annual", "yearly", "year", "total"}
_OPENSTAT_SOURCE = "openstat_psa"


@dataclass(frozen=True)
class PriceIndexStats:
    rows_seen: int = 0
    records_upserted: int = 0
    knowledge_upserted: int = 0


def _parse_year(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _parse_price(raw: str) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def normalize_csv_row(raw: dict[str, str], *, schema_version: str) -> dict[str, Any] | None:
    """Convert a raw OpenSTAT CSV row dict into the normalized payload shape."""
    geolocation = (raw.get("Geolocation") or "").strip()
    commodity_type = (raw.get("Commodity Type") or "").strip()
    commodity = (raw.get("Commodity") or commodity_type or "").strip()
    month = (raw.get("Month") or "").strip()
    year = _parse_year(raw.get("Year", ""))
    price = _parse_price(raw.get("Price", ""))

    if not geolocation or not commodity or year is None or not month:
        return None
    if month.lower() in _ANNUAL_MONTHS:
        return None

    payload: dict[str, Any] = {
        "geolocation": geolocation,
        "commodity_type": commodity_type,
        "commodity": commodity,
        "year": year,
        "month": month,
        "source": _OPENSTAT_SOURCE,
        "schema_version": schema_version,
    }
    if price is not None:
        payload["price_php_per_kg"] = price
    return payload


def iter_normalized_rows(csv_path: Path, *, schema_version: str) -> Iterator[dict[str, Any]]:
    with csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            normalized = normalize_csv_row(raw, schema_version=schema_version)
            if normalized is None:
                continue
            yield normalized


def _row_to_structured_point(row: dict[str, Any]) -> StructuredPoint:
    return StructuredPoint(
        point_id=build_price_point_id(
            str(row["geolocation"]),
            str(row["commodity"]),
            int(row["year"]),
            str(row["month"]),
        ),
        payload=row,
    )


def _row_to_knowledge_point(row: dict[str, Any]) -> KnowledgePoint:
    text = row_to_passage(row)
    payload = dict(row)
    payload["text"] = text
    payload["indexed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    return KnowledgePoint(
        point_id=build_price_point_id(
            str(row["geolocation"]),
            str(row["commodity"]),
            int(row["year"]),
            str(row["month"]),
        ),
        text=text,
        payload=payload,
    )


def _chunked(rows: Iterable[Any], size: int) -> Iterator[list[Any]]:
    batch: list[Any] = []
    for item in rows:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def run_price_indexer(
    *,
    csv_path: Path,
    store: QdrantStoreProtocol,
    settings: Settings,
    target_records: bool = True,
    target_knowledge: bool = True,
    batch_size: int = 256,
) -> PriceIndexStats:
    if not csv_path.is_file():
        raise FileNotFoundError(f"OpenSTAT CSV not found: {csv_path}")

    store.ensure_price_collections()

    rows_seen = 0
    records_upserted = 0
    knowledge_upserted = 0

    for batch in _chunked(
        iter_normalized_rows(csv_path, schema_version=settings.schema_version),
        size=batch_size,
    ):
        rows_seen += len(batch)
        if target_records:
            structured = [_row_to_structured_point(r) for r in batch]
            records_upserted += store.upsert_price_records(structured)
        if target_knowledge:
            knowledge = [_row_to_knowledge_point(r) for r in batch]
            knowledge_upserted += store.upsert_price_knowledge(knowledge)

    return PriceIndexStats(
        rows_seen=rows_seen,
        records_upserted=records_upserted,
        knowledge_upserted=knowledge_upserted,
    )
