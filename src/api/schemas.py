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
    municipalities_by_region_province: dict[str, dict[str, list[str]]]


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


class CorpusSearchRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"query": "rice variety recommendations", "limit": 5},
                {
                    "query": "PhilRice news on hybrid seeds",
                    "limit": 10,
                    "source_ids": ["philrice_news", "philrice"],
                    "min_score": 0.0,
                },
            ]
        },
    )

    query: Annotated[str, Field(min_length=1, max_length=2000, description="Natural-language query.")]
    limit: Annotated[int, Field(gt=0, le=50, description="Top-K hits to return.")] = 10
    source_ids: list[str] | None = Field(
        default=None,
        max_length=10,
        description="Optional filter to one or more corpus source ids.",
    )
    min_score: Annotated[float, Field(ge=0.0, le=1.0, description="Drop hits with fused score below this.")] = 0.0


class CorpusHit(BaseModel):
    score: float
    text: str
    source_id: str
    doc_id: str
    url: str | None = None
    title: str | None = None
    filename: str | None = None
    page: int | None = None


class CorpusSearchResponse(BaseModel):
    query: str
    limit: int
    source_ids: list[str] | None = None
    hits: list[CorpusHit]
    took_ms: float


class AgentMode(StrEnum):
    CHAT = "chat"
    TASKLIST = "tasklist"


class AgentUserType(StrEnum):
    FARMER = "farmer"
    DEVELOPER = "developer"
    ADMIN = "admin"


class AgentConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AgentChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"] = Field(description="Conversation message role.")
    content: Annotated[str, Field(min_length=1, max_length=4000)]


class AgentTask(BaseModel):
    status: Literal["pending", "in_progress", "completed", "cancelled"] = "pending"
    task: Annotated[str, Field(min_length=1, max_length=1000)]


class AgentToolCall(BaseModel):
    name: str
    arguments: dict[str, object] = Field(default_factory=dict)
    summary: str = ""
    result_count: int = 0


class AgentSource(BaseModel):
    source_id: str | None = None
    title: str | None = None
    url: str | None = None
    filename: str | None = None
    page: int | None = None
    snippet: str | None = None


class AgentWarning(BaseModel):
    code: Annotated[str, Field(min_length=1, max_length=100)]
    message: Annotated[str, Field(min_length=1, max_length=1000)]


class AgentChatRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "message": "Gawan mo ako ng tasklist para hanapin ang rice disease articles sa PhilRice at IRRI",
                    "mode": "tasklist",
                    "source_ids": ["philrice_news", "irri"],
                },
                {
                    "message": "Ano ang dapat kong i-check sa corpus RAG pipeline?",
                    "mode": "chat",
                },
            ]
        },
    )

    message: Annotated[str, Field(min_length=1, max_length=4000)]
    mode: AgentMode | None = Field(
        default=None,
        description="Optional response mode. Defaults to AGENT_DEFAULT_MODE.",
    )
    conversation_id: Annotated[str | None, Field(max_length=128)] = None
    session_id: Annotated[str | None, Field(max_length=128)] = None
    history: list[AgentChatMessage] = Field(default_factory=list, max_length=20)
    user_type: AgentUserType = Field(
        default=AgentUserType.FARMER,
        description="Primary user profile for response style and routing defaults.",
    )
    location: Annotated[str | None, Field(max_length=200)] = Field(
        default=None,
        description="Optional farmer location such as province, municipality, or region.",
    )
    crop: Annotated[str | None, Field(max_length=100)] = Field(
        default=None,
        description="Optional crop context, e.g. palay or corn.",
    )
    language: Annotated[str | None, Field(max_length=50)] = Field(
        default=None,
        description="Optional response language hint; otherwise inferred from message.",
    )
    source_ids: list[str] | None = Field(
        default=None,
        max_length=10,
        description="Optional source ids the agent may use in later tool-backed phases.",
    )
    max_tool_calls: Annotated[int | None, Field(ge=0, le=8)] = None


class AgentChatResponse(BaseModel):
    answer: str
    tasklist: list[AgentTask] = Field(default_factory=list)
    tool_calls: list[AgentToolCall] = Field(default_factory=list)
    sources: list[AgentSource] = Field(default_factory=list)
    warnings: list[AgentWarning] = Field(default_factory=list)
    confidence: AgentConfidence = AgentConfidence.LOW
    took_ms: float


class PriceRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    geolocation: str
    commodity_type: str
    commodity: str
    year: int
    month: str
    price_php_per_kg: float | None = None
    source: str = "openstat_psa"


class PriceListResponse(BaseModel):
    items: list[PriceRow]
    total: int
    next_offset: int | None = None


class PriceMetadataResponse(BaseModel):
    years: list[int]
    months: list[str]
    geolocations: list[str]
    commodity_types: list[str]
    commodities_by_type: dict[str, list[str]]


class PriceExtremum(BaseModel):
    value: float
    year: int
    month: str
    geolocation: str
    commodity: str


class PriceSummaryOverall(BaseModel):
    avg_price_php_per_kg: float
    min: PriceExtremum | None = None
    max: PriceExtremum | None = None
    row_count: int
    priced_row_count: int


class PriceSummaryByYear(BaseModel):
    year: int
    avg_price_php_per_kg: float
    row_count: int


class PriceSummaryByMonth(BaseModel):
    year: int
    month: str
    avg_price_php_per_kg: float
    row_count: int


class PriceSummaryScope(BaseModel):
    geolocation: str | None = None
    commodity_type: str | None = None
    commodity: str | None = None
    year_min: int | None = None
    year_max: int | None = None
    month: str | None = None


class PriceSummaryResponse(BaseModel):
    scope: PriceSummaryScope
    overall: PriceSummaryOverall
    by_year: list[PriceSummaryByYear]
    by_month: list[PriceSummaryByMonth]


class PriceFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    geolocation: str | None = None
    commodity_type: str | None = None
    commodity: str | None = None
    year_min: int | None = Field(default=None, ge=1900, le=2100)
    year_max: int | None = Field(default=None, ge=1900, le=2100)
    month: str | None = None


class PriceSearchRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"query": "palay farmgate price Abra 2023", "limit": 5},
                {
                    "query": "corn price CAR",
                    "limit": 10,
                    "filters": {"geolocation": "Abra", "year_min": 2020, "year_max": 2023},
                },
            ]
        },
    )

    query: Annotated[str, Field(min_length=1, max_length=2000)]
    limit: Annotated[int, Field(gt=0, le=100)] = 10
    filters: PriceFilters | None = None
    min_score: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0


class PriceHit(BaseModel):
    score: float
    text: str
    geolocation: str
    commodity_type: str
    commodity: str
    year: int
    month: str
    price_php_per_kg: float | None = None


class PriceSearchResponse(BaseModel):
    query: str
    filters: PriceFilters | None = None
    hits: list[PriceHit]
    took_ms: float


class RefreshPriceMetadataResponse(BaseModel):
    refreshed: bool
    years_count: int
    geolocations_count: int
    commodities_count: int
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
    openstat_source_file: str | None = None
    openstat_source_rows: int | None = None
    openstat_source_mtime: str | None = None


class RefreshMetadataResponse(BaseModel):
    refreshed: bool
    regions_count: int
    provinces_count: int
    municipalities_count: int
    years_count: int
    took_ms: float
