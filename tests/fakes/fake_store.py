"""In-memory implementation of :class:`QdrantStoreProtocol` for offline tests."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from copy import deepcopy
from typing import Any

from src.storage.qdrant_store import (
    CollectionStats,
    KnowledgeHitRecord,
    KnowledgePoint,
    QdrantStoreProtocol,
    StructuredPoint,
    YieldFilter,
)


def _matches(row: dict[str, Any], flt: YieldFilter) -> bool:
    if flt.year is not None and row.get("year") != flt.year:
        return False
    if flt.year_min is not None and (row.get("year") or 0) < flt.year_min:
        return False
    if flt.year_max is not None and (row.get("year") or 0) > flt.year_max:
        return False
    if flt.semester is not None and int(row.get("semester_code") or 0) != int(flt.semester):
        return False
    if flt.region and row.get("region") != flt.region:
        return False
    if flt.province and row.get("province") != flt.province:
        return False
    if flt.municipality and row.get("municipality") != flt.municipality:
        return False
    yield_value = float(row.get("avg_yield_ton_ha") or 0.0)
    if flt.min_yield is not None and yield_value < flt.min_yield:
        return False
    if flt.max_yield is not None and yield_value > flt.max_yield:
        return False
    return True


class FakeQdrantStore(QdrantStoreProtocol):
    """In-memory store; payloads are deep-copied to keep tests isolated."""

    def __init__(self, *, reachable: bool = True) -> None:
        self.reachable = reachable
        self.records: dict[str, dict[str, Any]] = {}
        self.knowledge: dict[str, dict[str, Any]] = {}
        self.created_collections = False

    def seed(self, rows: Iterable[dict[str, Any]]) -> None:
        from src.storage.qdrant_store import build_point_id

        for row in rows:
            point_id = build_point_id(
                year=int(row["year"]),
                semester_code=int(row["semester_code"]),
                region=str(row["region"]),
                province=str(row["province"]),
                municipality=str(row.get("municipality") or ""),
            )
            self.records[point_id] = deepcopy(row)
            knowledge_payload = deepcopy(row)
            knowledge_payload.setdefault("text", f"row about {row['municipality']} {row['year']}")
            self.knowledge[point_id] = knowledge_payload

    def ping(self) -> bool:
        return self.reachable

    def list_collection_names(self) -> list[str]:
        return ["prism_yield_records", "prism_yield_knowledge"]

    def ensure_collections(self) -> None:
        self.created_collections = True

    def count_yield_rows(self, flt: YieldFilter) -> int:
        return sum(1 for r in self.records.values() if _matches(r, flt))

    def scroll_yield_rows(
        self,
        flt: YieldFilter,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int | None]:
        ordered = [deepcopy(r) for r in self.records.values() if _matches(r, flt)]
        sliced = ordered[offset : offset + limit]
        next_offset = offset + limit if len(ordered) > offset + limit else None
        return sliced, next_offset

    def iter_yield_rows(
        self,
        flt: YieldFilter,
        max_rows: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        emitted = 0
        for row in self.records.values():
            if not _matches(row, flt):
                continue
            yield deepcopy(row)
            emitted += 1
            if max_rows is not None and emitted >= max_rows:
                return

    def hybrid_search(
        self,
        query_text: str,
        flt: YieldFilter,
        limit: int,
        min_score: float,
    ) -> list[KnowledgeHitRecord]:
        ranked: list[tuple[float, dict[str, Any]]] = []
        tokens = {t.lower() for t in query_text.split() if t}
        for payload in self.knowledge.values():
            if not _matches(payload, flt):
                continue
            haystack = " ".join(str(v).lower() for v in payload.values() if v is not None)
            overlap = sum(1 for token in tokens if token in haystack)
            score = overlap / max(len(tokens), 1)
            if score >= min_score:
                ranked.append((score, deepcopy(payload)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [KnowledgeHitRecord(score=s, payload=p) for s, p in ranked[:limit]]

    def upsert_yield_records(self, points: Iterable[StructuredPoint]) -> int:
        count = 0
        for point in points:
            self.records[point.point_id] = deepcopy(point.payload)
            count += 1
        return count

    def upsert_yield_knowledge(self, points: Iterable[KnowledgePoint]) -> int:
        count = 0
        for point in points:
            payload = deepcopy(point.payload)
            payload.setdefault("text", point.text)
            self.knowledge[point.point_id] = payload
            count += 1
        return count

    def collection_stats(self) -> list[CollectionStats]:
        return [
            CollectionStats(
                name="prism_yield_records",
                points=len(self.records),
                schema_version="v1",
                vectors=None,
            ),
            CollectionStats(
                name="prism_yield_knowledge",
                points=len(self.knowledge),
                schema_version="v1",
                vectors=["dense", "sparse"],
            ),
        ]
