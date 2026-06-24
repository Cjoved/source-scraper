"""In-memory implementation of :class:`QdrantStoreProtocol` for offline tests."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from copy import deepcopy
from typing import Any

from src.storage.qdrant_store import (
    CollectionStats,
    CorpusFilter,
    CorpusPoint,
    KnowledgeHitRecord,
    KnowledgePoint,
    PriceFilter,
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


def _matches_price(row: dict[str, Any], flt: PriceFilter) -> bool:
    if flt.geolocation and row.get("geolocation") != flt.geolocation:
        return False
    if flt.commodity_type and row.get("commodity_type") != flt.commodity_type:
        return False
    if flt.commodity and row.get("commodity") != flt.commodity:
        return False
    if flt.year is not None and row.get("year") != flt.year:
        return False
    if flt.year_min is not None and (row.get("year") or 0) < flt.year_min:
        return False
    if flt.year_max is not None and (row.get("year") or 0) > flt.year_max:
        return False
    if flt.month and row.get("month") != flt.month:
        return False
    price_value = row.get("price_php_per_kg")
    if price_value is not None:
        price_float = float(price_value)
        if flt.min_price is not None and price_float < flt.min_price:
            return False
        if flt.max_price is not None and price_float > flt.max_price:
            return False
    elif flt.min_price is not None or flt.max_price is not None:
        return False
    return True


class FakeQdrantStore(QdrantStoreProtocol):
    """In-memory store; payloads are deep-copied to keep tests isolated."""

    def __init__(self, *, reachable: bool = True) -> None:
        self.reachable = reachable
        self.records: dict[str, dict[str, Any]] = {}
        self.knowledge: dict[str, dict[str, Any]] = {}
        self.price_records: dict[str, dict[str, Any]] = {}
        self.price_knowledge: dict[str, dict[str, Any]] = {}
        self.corpus: dict[str, dict[str, Any]] = {}
        self.created_collections = False
        self.price_collections_created = False
        self.corpus_collection_created = False

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
        names = [
            "prism_yield_records",
            "prism_yield_knowledge",
            "openstat_price_records",
            "openstat_price_knowledge",
        ]
        if self.corpus_collection_created or self.corpus:
            names.append("agri_corpus_rag")
        return names

    def ensure_collections(self) -> None:
        self.created_collections = True

    def ensure_price_collections(self) -> None:
        self.price_collections_created = True

    def ensure_corpus_collection(self, *, recreate: bool = False) -> None:
        if recreate:
            self.corpus.clear()
        self.corpus_collection_created = True

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

    def seed_prices(self, rows: Iterable[dict[str, Any]]) -> None:
        from src.storage.qdrant_store import build_price_point_id

        for row in rows:
            point_id = build_price_point_id(
                str(row["geolocation"]),
                str(row["commodity"]),
                int(row["year"]),
                str(row["month"]),
            )
            self.price_records[point_id] = deepcopy(row)
            knowledge_payload = deepcopy(row)
            knowledge_payload.setdefault(
                "text",
                f"price for {row['commodity']} in {row['geolocation']} {row['month']} {row['year']}",
            )
            self.price_knowledge[point_id] = knowledge_payload

    def count_price_rows(self, flt: PriceFilter) -> int:
        return sum(1 for r in self.price_records.values() if _matches_price(r, flt))

    def scroll_price_rows(
        self,
        flt: PriceFilter,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int | None]:
        ordered = [deepcopy(r) for r in self.price_records.values() if _matches_price(r, flt)]
        sliced = ordered[offset : offset + limit]
        next_offset = offset + limit if len(ordered) > offset + limit else None
        return sliced, next_offset

    def iter_price_rows(
        self,
        flt: PriceFilter,
        max_rows: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        emitted = 0
        for row in self.price_records.values():
            if not _matches_price(row, flt):
                continue
            yield deepcopy(row)
            emitted += 1
            if max_rows is not None and emitted >= max_rows:
                return

    def search_prices(
        self,
        query_text: str,
        flt: PriceFilter,
        limit: int,
        min_score: float,
    ) -> list[KnowledgeHitRecord]:
        ranked: list[tuple[float, dict[str, Any]]] = []
        tokens = {t.lower() for t in query_text.split() if t}
        for payload in self.price_knowledge.values():
            if not _matches_price(payload, flt):
                continue
            haystack = " ".join(str(v).lower() for v in payload.values() if v is not None)
            overlap = sum(1 for token in tokens if token in haystack)
            score = overlap / max(len(tokens), 1)
            if score >= min_score:
                ranked.append((score, deepcopy(payload)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [KnowledgeHitRecord(score=s, payload=p) for s, p in ranked[:limit]]

    def upsert_price_records(self, points: Iterable[StructuredPoint]) -> int:
        count = 0
        for point in points:
            self.price_records[point.point_id] = deepcopy(point.payload)
            count += 1
        return count

    def upsert_price_knowledge(self, points: Iterable[KnowledgePoint]) -> int:
        count = 0
        for point in points:
            payload = deepcopy(point.payload)
            payload.setdefault("text", point.text)
            self.price_knowledge[point.point_id] = payload
            count += 1
        return count

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

    def upsert_corpus(self, points: Iterable[CorpusPoint]) -> int:
        count = 0
        for point in points:
            payload = deepcopy(point.payload)
            payload.setdefault("text", point.text)
            self.corpus[point.point_id] = payload
            count += 1
        return count

    def search_corpus(
        self,
        query_text: str,
        flt: CorpusFilter,
        limit: int,
        min_score: float,
    ) -> list[KnowledgeHitRecord]:
        ranked: list[tuple[float, dict[str, Any]]] = []
        tokens = {t.lower() for t in query_text.split() if t}
        for payload in self.corpus.values():
            if flt.source_ids and payload.get("source_id") not in flt.source_ids:
                continue
            haystack = " ".join(str(v).lower() for v in payload.values() if v is not None)
            overlap = sum(1 for token in tokens if token in haystack)
            score = overlap / max(len(tokens), 1)
            if score >= min_score:
                ranked.append((score, deepcopy(payload)))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [KnowledgeHitRecord(score=s, payload=p) for s, p in ranked[:limit]]

    def iter_corpus_rows(
        self,
        flt: CorpusFilter,
        max_rows: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        emitted = 0
        for payload in self.corpus.values():
            if flt.source_ids and payload.get("source_id") not in flt.source_ids:
                continue
            yield deepcopy(payload)
            emitted += 1
            if max_rows is not None and emitted >= max_rows:
                return

    def seed_corpus(self, rows: Iterable[dict[str, Any]]) -> None:
        from src.storage.qdrant_store import build_corpus_point_id

        for row in rows:
            source_id = str(row["source_id"])
            doc_id = str(row["doc_id"])
            point_id = build_corpus_point_id(source_id, doc_id)
            self.corpus[point_id] = deepcopy(row)

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
            CollectionStats(
                name="openstat_price_records",
                points=len(self.price_records),
                schema_version="v1",
                vectors=None,
            ),
            CollectionStats(
                name="openstat_price_knowledge",
                points=len(self.price_knowledge),
                schema_version="v1",
                vectors=["dense", "sparse"],
            ),
            CollectionStats(
                name="agri_corpus_rag",
                points=len(self.corpus),
                schema_version="v1",
                vectors=["dense", "sparse"],
            ),
        ]
