"""Pydantic v2 request/response models used by API routes.

Domain types in `services/` stay framework-agnostic; this module is the only
place Pydantic schemas live and the only place HTTP-shaped types are exposed.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SemesterCode(IntEnum):
    FIRST = 1
    SECOND = 2


class ExportFormat(StrEnum):
    NDJSON = "ndjson"
    CSV = "csv"


class YieldRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    year: int
    semester_code: SemesterCode
    semester_label: str
    region: str
    province: str
    municipality: str
    avg_yield_ton_ha: float
    scraped_at: str
    source: str = "prism_yield_export"


class YieldListResponse(BaseModel):
    items: list[YieldRow]
    total: int
    next_offset: int | None = None


class SemesterMetadata(BaseModel):
    code: SemesterCode
    label: str


class YieldMetadataResponse(BaseModel):
    years: list[int]
    semesters: list[SemesterMetadata]
    regions: list[str]
    provinces_by_region: dict[str, list[str]]


class YieldExtremum(BaseModel):
    value: float
    year: int
    semester_code: SemesterCode
    region: str
    province: str
    municipality: str


class SummaryOverall(BaseModel):
    avg_yield_ton_ha: float
    min: YieldExtremum | None = None
    max: YieldExtremum | None = None
    row_count: int
    municipality_count: int


class SummaryByYear(BaseModel):
    year: int
    avg_yield_ton_ha: float
    row_count: int


class SummaryBySemester(BaseModel):
    year: int
    semester_code: SemesterCode
    avg_yield_ton_ha: float
    row_count: int


class SummaryScope(BaseModel):
    region: str | None = None
    province: str | None = None
    municipality: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    semester: SemesterCode | None = None


class YieldSummaryResponse(BaseModel):
    scope: SummaryScope
    overall: SummaryOverall
    by_year: list[SummaryByYear]
    by_semester: list[SummaryBySemester]


class KnowledgeFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: str | None = None
    province: str | None = None
    municipality: str | None = None
    year_min: int | None = Field(default=None, ge=1900, le=2100)
    year_max: int | None = Field(default=None, ge=1900, le=2100)
    semester: SemesterCode | None = None


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "query": "Bangued Abra 2018 first sem",
                    "limit": 5,
                    "min_score": 0.0,
                },
                {
                    "query": "rice yield trends",
                    "limit": 10,
                    "filters": {
                        "region": "CAR",
                        "year_min": 2020,
                        "year_max": 2023,
                    },
                    "min_score": 0.3,
                },
            ]
        },
    )

    query: Annotated[str, Field(min_length=1, max_length=2000, description="Natural-language query.")]
    limit: Annotated[int, Field(gt=0, le=100, description="Top-K hits to return.")] = 10
    filters: KnowledgeFilters | None = Field(default=None, description="Optional pre-filter scope.")
    min_score: Annotated[float, Field(ge=0.0, le=1.0, description="Drop hits with fused score below this.")] = 0.0


class KnowledgeHit(BaseModel):
    score: float
    text: str
    year: int
    semester_code: SemesterCode
    semester_label: str
    region: str
    province: str
    municipality: str
    avg_yield_ton_ha: float


class KnowledgeSearchResponse(BaseModel):
    query: str
    filters: KnowledgeFilters | None = None
    hits: list[KnowledgeHit]
    took_ms: float


class HealthResponse(BaseModel):
    status: Literal["ok"]
    qdrant: Literal["reachable", "unreachable"]
    collections: list[str]


class CollectionStatus(BaseModel):
    name: str
    points: int
    schema_version: str
    vectors: list[str] | None = None
    indexed_at: str | None = None


class IndexStatusResponse(BaseModel):
    collections: list[CollectionStatus]
    source_file: str
    source_rows: int | None = None
    source_mtime: str | None = None


class RefreshMetadataResponse(BaseModel):
    refreshed: bool
    regions_count: int
    provinces_count: int
    municipalities_count: int
    years_count: int
    took_ms: float
