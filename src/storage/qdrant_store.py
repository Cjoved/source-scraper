"""Qdrant adapter.

Two collections are managed here:

- ``prism_yield_records``: structured rows with a dummy 1-d vector, queried via
  ``scroll`` + ``count``. The aggregation, listing, and export endpoints all
  read through this collection.
- ``prism_yield_knowledge``: textified rows with **named vectors** ``dense``
  (FastEmbed dense model) and ``sparse`` (BM25). The knowledge search endpoint
  queries this collection with prefetch on both vectors fused via RRF.

The concrete :class:`QdrantStore` is a thin wrapper around
:class:`qdrant_client.QdrantClient`. A :class:`QdrantStoreProtocol` is defined
so route handlers and services can depend on the interface instead of the
concrete class, enabling offline tests with a fake.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from src.api.errors import ApiError, ErrorCode
from src.api.schemas import SemesterCode
from src.api.settings import Settings


@dataclass(frozen=True)
class YieldFilter:
    """Filter parameters shared by listing, aggregation, export, and search."""

    year: int | None = None
    year_min: int | None = None
    year_max: int | None = None
    semester: SemesterCode | None = None
    region: str | None = None
    province: str | None = None
    municipality: str | None = None
    min_yield: float | None = None
    max_yield: float | None = None


@dataclass(frozen=True)
class StructuredPoint:
    point_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class KnowledgePoint:
    point_id: str
    text: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class KnowledgeHitRecord:
    score: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class CollectionStats:
    name: str
    points: int
    schema_version: str
    vectors: list[str] | None


_DUMMY_VECTOR: list[float] = [0.0]

_POINT_ID_NAMESPACE = uuid.UUID("8b9c2d4a-1f3e-4b7c-9a5d-6e8f0a1b2c3d")


def build_point_id(
    year: int,
    semester_code: int,
    region: str,
    province: str,
    municipality: str,
) -> str:
    """Deterministic UUIDv5 point ID stable across re-indexing.

    Qdrant accepts unsigned integers or UUID strings as point IDs. A
    namespaced UUIDv5 over the canonical row key gives us both stability
    (same input -> same UUID) and a Qdrant-valid format.
    """
    raw = f"{year}|{semester_code}|{region}|{province}|{municipality}"
    return str(uuid.uuid5(_POINT_ID_NAMESPACE, raw))


class QdrantStoreProtocol(Protocol):
    def ping(self) -> bool: ...

    def list_collection_names(self) -> list[str]: ...

    def ensure_collections(self) -> None: ...

    def count_yield_rows(self, flt: YieldFilter) -> int: ...

    def scroll_yield_rows(
        self,
        flt: YieldFilter,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int | None]: ...

    def iter_yield_rows(
        self,
        flt: YieldFilter,
        max_rows: int | None = None,
    ) -> Iterator[dict[str, Any]]: ...

    def hybrid_search(
        self,
        query_text: str,
        flt: YieldFilter,
        limit: int,
        min_score: float,
    ) -> list[KnowledgeHitRecord]: ...

    def upsert_yield_records(self, points: Iterable[StructuredPoint]) -> int: ...

    def upsert_yield_knowledge(self, points: Iterable[KnowledgePoint]) -> int: ...

    def collection_stats(self) -> list[CollectionStats]: ...


class QdrantStore:
    """Concrete Qdrant-backed implementation of :class:`QdrantStoreProtocol`.

    Imports of ``qdrant_client`` happen lazily so the project remains usable
    (e.g., scraper-only mode) without the ``api`` extras installed.
    """

    def __init__(self, settings: Settings) -> None:
        from qdrant_client import QdrantClient

        self._settings = settings
        self._client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=settings.qdrant_timeout_seconds,
            local_inference_batch_size=settings.qdrant_local_inference_batch_size,
        )
        self._client.set_model(settings.embedding_dense_model)
        self._client.set_sparse_model(settings.embedding_sparse_model)

    @property
    def records_name(self) -> str:
        return self._settings.qdrant_records_collection

    @property
    def knowledge_name(self) -> str:
        return self._settings.qdrant_knowledge_collection

    def ping(self) -> bool:
        try:
            self._client.get_collections()
        except Exception:
            return False
        return True

    def list_collection_names(self) -> list[str]:
        try:
            response = self._client.get_collections()
        except Exception as exc:
            raise ApiError(
                ErrorCode.QDRANT_UNAVAILABLE,
                "Qdrant is unreachable",
                status_code=503,
                headers={"Retry-After": "30"},
                details={"reason": exc.__class__.__name__},
            ) from exc
        return [c.name for c in response.collections]

    def ensure_collections(self) -> None:
        from qdrant_client.models import (
            Distance,
            PayloadSchemaType,
            VectorParams,
        )

        existing = set(self.list_collection_names())

        if self.records_name not in existing:
            self._client.create_collection(
                collection_name=self.records_name,
                vectors_config=VectorParams(size=1, distance=Distance.COSINE),
            )
        self._create_payload_indexes(self.records_name)

        if self.knowledge_name not in existing:
            dense_name = self._settings.embedding_dense_model
            sparse_name = self._settings.embedding_sparse_model
            vectors_config = self._client.get_fastembed_vector_params()
            sparse_config = self._client.get_fastembed_sparse_vector_params()
            self._client.create_collection(
                collection_name=self.knowledge_name,
                vectors_config=vectors_config,
                sparse_vectors_config=sparse_config,
            )
            _ = (dense_name, sparse_name)
        self._create_payload_indexes(self.knowledge_name)

        del PayloadSchemaType

    def _create_payload_indexes(self, collection: str) -> None:
        from qdrant_client.models import PayloadSchemaType

        fields: dict[str, PayloadSchemaType] = {
            "year": PayloadSchemaType.INTEGER,
            "semester_code": PayloadSchemaType.INTEGER,
            "region": PayloadSchemaType.KEYWORD,
            "province": PayloadSchemaType.KEYWORD,
            "municipality": PayloadSchemaType.KEYWORD,
            "avg_yield_ton_ha": PayloadSchemaType.FLOAT,
        }
        for field_name, schema_type in fields.items():
            try:
                self._client.create_payload_index(
                    collection_name=collection,
                    field_name=field_name,
                    field_schema=schema_type,
                )
            except Exception:
                continue

    def _build_qdrant_filter(self, flt: YieldFilter) -> Any | None:
        from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

        must: list[Any] = []

        if flt.year is not None:
            must.append(FieldCondition(key="year", match=MatchValue(value=flt.year)))
        if flt.year_min is not None or flt.year_max is not None:
            rng = Range(gte=flt.year_min, lte=flt.year_max)
            must.append(FieldCondition(key="year", range=rng))
        if flt.semester is not None:
            must.append(
                FieldCondition(key="semester_code", match=MatchValue(value=int(flt.semester)))
            )
        if flt.region:
            must.append(FieldCondition(key="region", match=MatchValue(value=flt.region)))
        if flt.province:
            must.append(FieldCondition(key="province", match=MatchValue(value=flt.province)))
        if flt.municipality:
            must.append(
                FieldCondition(key="municipality", match=MatchValue(value=flt.municipality))
            )
        if flt.min_yield is not None or flt.max_yield is not None:
            rng = Range(gte=flt.min_yield, lte=flt.max_yield)
            must.append(FieldCondition(key="avg_yield_ton_ha", range=rng))

        if not must:
            return None
        return Filter(must=must)

    def count_yield_rows(self, flt: YieldFilter) -> int:
        try:
            result = self._client.count(
                collection_name=self.records_name,
                count_filter=self._build_qdrant_filter(flt),
                exact=True,
            )
        except Exception as exc:
            raise self._wrap_qdrant_error(exc) from exc
        return int(result.count)

    def scroll_yield_rows(
        self,
        flt: YieldFilter,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int | None]:
        try:
            points, _ = self._client.scroll(
                collection_name=self.records_name,
                scroll_filter=self._build_qdrant_filter(flt),
                limit=limit + offset,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as exc:
            raise self._wrap_qdrant_error(exc) from exc
        sliced = points[offset : offset + limit]
        next_offset = offset + limit if len(points) > offset + limit else None
        return [dict(p.payload or {}) for p in sliced], next_offset

    def iter_yield_rows(
        self,
        flt: YieldFilter,
        max_rows: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        page_size = 512
        next_page_token: Any = None
        emitted = 0
        qdrant_filter = self._build_qdrant_filter(flt)

        while True:
            try:
                points, next_page_token = self._client.scroll(
                    collection_name=self.records_name,
                    scroll_filter=qdrant_filter,
                    limit=page_size,
                    offset=next_page_token,
                    with_payload=True,
                    with_vectors=False,
                )
            except Exception as exc:
                raise self._wrap_qdrant_error(exc) from exc

            for point in points:
                yield dict(point.payload or {})
                emitted += 1
                if max_rows is not None and emitted >= max_rows:
                    return

            if next_page_token is None or not points:
                return

    def hybrid_search(
        self,
        query_text: str,
        flt: YieldFilter,
        limit: int,
        min_score: float,
    ) -> list[KnowledgeHitRecord]:
        """Run true hybrid retrieval over the knowledge collection.

        Dense and sparse prefetches are over-fetched independently and fused
        with Reciprocal Rank Fusion (or DBSF if configured). The text is
        wrapped in ``models.Document`` so qdrant-client performs FastEmbed
        inference server-side via the modern ``query_points`` API.
        """
        from qdrant_client import models

        dense_name = self._client.get_vector_field_name()
        sparse_name = self._client.get_sparse_vector_field_name()
        qfilter = self._build_qdrant_filter(flt)
        prefetch_limit = max(limit * self._settings.hybrid_prefetch_multiplier, limit)
        fusion = (
            models.Fusion.RRF
            if self._settings.hybrid_fusion == "rrf"
            else models.Fusion.DBSF
        )

        prefetch: list[Any] = []
        if dense_name:
            prefetch.append(
                models.Prefetch(
                    query=models.Document(
                        text=query_text,
                        model=self._settings.embedding_dense_model,
                    ),
                    using=dense_name,
                    limit=prefetch_limit,
                    filter=qfilter,
                )
            )
        if sparse_name:
            prefetch.append(
                models.Prefetch(
                    query=models.Document(
                        text=query_text,
                        model=self._settings.embedding_sparse_model,
                    ),
                    using=sparse_name,
                    limit=prefetch_limit,
                    filter=qfilter,
                )
            )

        try:
            response = self._client.query_points(
                collection_name=self.knowledge_name,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=fusion),
                query_filter=qfilter,
                limit=limit,
                with_payload=True,
            )
        except Exception as exc:
            raise self._wrap_qdrant_error(exc) from exc

        hits: list[KnowledgeHitRecord] = []
        for point in response.points:
            score = float(getattr(point, "score", 0.0) or 0.0)
            if score < min_score:
                continue
            payload = dict(getattr(point, "payload", None) or {})
            hits.append(KnowledgeHitRecord(score=score, payload=payload))
        return hits

    def upsert_yield_records(self, points: Iterable[StructuredPoint]) -> int:
        from qdrant_client.models import PointStruct

        batch = [
            PointStruct(id=p.point_id, vector=_DUMMY_VECTOR, payload=p.payload)
            for p in points
        ]
        if not batch:
            return 0
        try:
            self._client.upsert(collection_name=self.records_name, points=batch)
        except Exception as exc:
            raise self._wrap_qdrant_error(exc) from exc
        return len(batch)

    def upsert_yield_knowledge(self, points: Iterable[KnowledgePoint]) -> int:
        materialized = list(points)
        if not materialized:
            return 0
        documents = [p.text for p in materialized]
        metadata = [p.payload for p in materialized]
        ids = [p.point_id for p in materialized]
        try:
            self._client.add(
                collection_name=self.knowledge_name,
                documents=documents,
                metadata=metadata,
                ids=ids,
            )
        except Exception as exc:
            raise self._wrap_qdrant_error(exc) from exc
        return len(materialized)

    def collection_stats(self) -> list[CollectionStats]:
        out: list[CollectionStats] = []
        for name, vectors in (
            (self.records_name, None),
            (self.knowledge_name, ["dense", "sparse"]),
        ):
            try:
                info = self._client.count(collection_name=name, exact=True)
                count = int(info.count)
            except Exception:
                count = 0
            out.append(
                CollectionStats(
                    name=name,
                    points=count,
                    schema_version=self._settings.schema_version,
                    vectors=vectors,
                )
            )
        return out

    def _wrap_qdrant_error(self, exc: Exception) -> ApiError:
        return ApiError(
            ErrorCode.QDRANT_UNAVAILABLE,
            "Qdrant request failed",
            status_code=503,
            headers={"Retry-After": "30"},
            details={"reason": exc.__class__.__name__},
        )
