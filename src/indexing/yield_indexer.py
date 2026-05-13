"""One-pass yield CSV indexer.

For each CSV row the indexer produces:

- a :class:`StructuredPoint` for ``prism_yield_records`` (payload-only) and
- a :class:`KnowledgePoint` for ``prism_yield_knowledge`` (textified + payload).

Both points share the same deterministic ID so the two collections stay in sync
and re-indexing is idempotent. Batches are flushed by row count to keep memory
bounded for large CSVs.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.api.settings import Settings
from src.scraper.prism_constants import SEMESTERS
from src.services.textify import row_to_passage
from src.storage.qdrant_store import (
    KnowledgePoint,
    QdrantStoreProtocol,
    StructuredPoint,
    build_point_id,
)


@dataclass(frozen=True)
class IndexStats:
    rows_seen: int = 0
    records_upserted: int = 0
    knowledge_upserted: int = 0


_SEMESTER_LABEL_TO_CODE = {label: int(code) for code, label in SEMESTERS}


def _parse_semester(label: str) -> int | None:
    label = label.strip()
    if not label:
        return None
    if label in _SEMESTER_LABEL_TO_CODE:
        return _SEMESTER_LABEL_TO_CODE[label]
    lowered = label.lower()
    if "1st" in lowered or "first" in lowered:
        return 1
    if "2nd" in lowered or "second" in lowered:
        return 2
    return None


def _parse_year(raw: str) -> int | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_yield(raw: str) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _normalize_scraped_at(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    raw = raw.replace(" ", "T")
    return raw


def normalize_csv_row(raw: dict[str, str], *, schema_version: str) -> dict[str, Any] | None:
    """Convert a raw CSV row dict into the normalized payload shape."""
    year = _parse_year(raw.get("Year", ""))
    sem_label = raw.get("Semester", "").strip()
    sem_code = _parse_semester(sem_label)
    avg_yield = _parse_yield(raw.get("Average Yield (ton/ha)", ""))
    region = raw.get("Region", "").strip()
    province = raw.get("Province", "").strip()
    municipality = raw.get("Municipality", "").strip()
    scraped_at = _normalize_scraped_at(raw.get("Date and time of Scraping", ""))

    if year is None or sem_code is None or avg_yield is None:
        return None
    if not region or not province:
        return None

    return {
        "year": year,
        "semester_code": sem_code,
        "semester_label": sem_label,
        "region": region,
        "province": province,
        "municipality": municipality,
        "avg_yield_ton_ha": round(float(avg_yield), 4),
        "scraped_at": scraped_at,
        "source": "prism_yield_export",
        "schema_version": schema_version,
    }


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
        point_id=build_point_id(
            year=int(row["year"]),
            semester_code=int(row["semester_code"]),
            region=str(row["region"]),
            province=str(row["province"]),
            municipality=str(row["municipality"]),
        ),
        payload=row,
    )


def _row_to_knowledge_point(row: dict[str, Any]) -> KnowledgePoint:
    text = row_to_passage(row)
    payload = dict(row)
    payload["text"] = text
    payload["indexed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    return KnowledgePoint(
        point_id=build_point_id(
            year=int(row["year"]),
            semester_code=int(row["semester_code"]),
            region=str(row["region"]),
            province=str(row["province"]),
            municipality=str(row["municipality"]),
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


def run_indexer(
    *,
    csv_path: Path,
    store: QdrantStoreProtocol,
    settings: Settings,
    target_records: bool = True,
    target_knowledge: bool = True,
    batch_size: int = 256,
) -> IndexStats:
    if not csv_path.is_file():
        raise FileNotFoundError(f"Yield CSV not found: {csv_path}")

    store.ensure_collections()

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
            records_upserted += store.upsert_yield_records(structured)
        if target_knowledge:
            knowledge = [_row_to_knowledge_point(r) for r in batch]
            knowledge_upserted += store.upsert_yield_knowledge(knowledge)

    return IndexStats(
        rows_seen=rows_seen,
        records_upserted=records_upserted,
        knowledge_upserted=knowledge_upserted,
    )
