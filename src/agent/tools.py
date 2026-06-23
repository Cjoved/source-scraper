"""Read-only LangChain tools for the API agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from src.api.schemas import AgentSource, PriceSummaryScope, SemesterCode, SummaryScope
from src.services.aggregation import aggregate_rows
from src.services.filters import build_yield_filter
from src.services.price_aggregation import aggregate_price_rows
from src.services.price_filters import build_price_filter
from src.storage.qdrant_store import CorpusFilter, QdrantStoreProtocol

MAX_TOOL_LIMIT = 10
SNIPPET_CHARS = 500


@dataclass(frozen=True)
class ToolExecutionContext:
    store: QdrantStoreProtocol
    min_score: float = 0.0


@dataclass(frozen=True)
class ToolExecutionResult:
    name: str
    arguments: dict[str, Any]
    summary: str
    result_count: int
    payload: dict[str, Any]
    sources: list[AgentSource]


class SearchCorpusArgs(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    source_ids: list[str] | None = Field(default=None, max_length=10)
    limit: int = Field(default=5, ge=1, le=MAX_TOOL_LIMIT)


class SearchYieldKnowledgeArgs(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    region: str | None = None
    province: str | None = None
    municipality: str | None = None
    year_min: int | None = Field(default=None, ge=1900, le=2100)
    year_max: int | None = Field(default=None, ge=1900, le=2100)
    semester: int | None = Field(default=None, ge=1, le=2)
    limit: int = Field(default=5, ge=1, le=MAX_TOOL_LIMIT)


class SummarizeYieldArgs(BaseModel):
    region: str | None = None
    province: str | None = None
    municipality: str | None = None
    year_min: int | None = Field(default=None, ge=1900, le=2100)
    year_max: int | None = Field(default=None, ge=1900, le=2100)
    semester: int | None = Field(default=None, ge=1, le=2)


class SearchPricesArgs(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    geolocation: str | None = None
    commodity_type: str | None = None
    commodity: str | None = None
    year_min: int | None = Field(default=None, ge=1900, le=2100)
    year_max: int | None = Field(default=None, ge=1900, le=2100)
    month: str | None = None
    limit: int = Field(default=5, ge=1, le=MAX_TOOL_LIMIT)


class SummarizePricesArgs(BaseModel):
    geolocation: str | None = None
    commodity_type: str | None = None
    commodity: str | None = None
    year_min: int | None = Field(default=None, ge=1900, le=2100)
    year_max: int | None = Field(default=None, ge=1900, le=2100)
    month: str | None = None


def _snippet(value: object) -> str:
    text = str(value or "").strip()
    return text[:SNIPPET_CHARS]


def _semester(value: int | None) -> SemesterCode | None:
    return SemesterCode(value) if value in (1, 2) else None


def _source_from_payload(payload: dict[str, Any], *, source_id: str) -> AgentSource:
    return AgentSource(
        source_id=str(payload.get("source_id") or source_id),
        title=str(payload["title"]) if payload.get("title") else None,
        url=str(payload["url"]) if payload.get("url") else None,
        filename=str(payload["filename"]) if payload.get("filename") else None,
        page=int(payload["page"]) if payload.get("page") is not None else None,
        snippet=_snippet(payload.get("text") or payload),
    )


def _search_corpus_impl(
    ctx: ToolExecutionContext,
    *,
    query: str,
    source_ids: list[str] | None = None,
    limit: int = 5,
) -> ToolExecutionResult:
    flt = CorpusFilter(source_ids=tuple(source_ids) if source_ids else None)
    hits = ctx.store.search_corpus(
        query_text=query,
        flt=flt,
        limit=limit,
        min_score=ctx.min_score,
    )
    payloads = [{"score": hit.score, **hit.payload} for hit in hits]
    sources = [_source_from_payload(hit.payload, source_id="agri_corpus_rag") for hit in hits]
    return ToolExecutionResult(
        name="search_corpus",
        arguments={"query": query, "source_ids": source_ids, "limit": limit},
        summary=f"Found {len(hits)} corpus hit(s).",
        result_count=len(hits),
        payload={"hits": payloads},
        sources=sources,
    )


def _search_yield_knowledge_impl(
    ctx: ToolExecutionContext,
    *,
    query: str,
    region: str | None = None,
    province: str | None = None,
    municipality: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    semester: int | None = None,
    limit: int = 5,
) -> ToolExecutionResult:
    flt = build_yield_filter(
        region=region,
        province=province,
        municipality=municipality,
        year_min=year_min,
        year_max=year_max,
        semester=_semester(semester),
    )
    hits = ctx.store.hybrid_search(query_text=query, flt=flt, limit=limit, min_score=ctx.min_score)
    payloads = [{"score": hit.score, **hit.payload} for hit in hits]
    sources = [_source_from_payload(hit.payload, source_id="prism_yield_knowledge") for hit in hits]
    return ToolExecutionResult(
        name="search_yield_knowledge",
        arguments={
            "query": query,
            "region": region,
            "province": province,
            "municipality": municipality,
            "year_min": year_min,
            "year_max": year_max,
            "semester": semester,
            "limit": limit,
        },
        summary=f"Found {len(hits)} yield knowledge hit(s).",
        result_count=len(hits),
        payload={"hits": payloads},
        sources=sources,
    )


def _summarize_yield_impl(
    ctx: ToolExecutionContext,
    *,
    region: str | None = None,
    province: str | None = None,
    municipality: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    semester: int | None = None,
) -> ToolExecutionResult:
    sem = _semester(semester)
    flt = build_yield_filter(
        region=region,
        province=province,
        municipality=municipality,
        year_min=year_min,
        year_max=year_max,
        semester=sem,
    )
    scope = SummaryScope(
        region=region,
        province=province,
        municipality=municipality,
        year_min=year_min,
        year_max=year_max,
        semester=sem,
    )
    rows = list(ctx.store.iter_yield_rows(flt))
    summary = aggregate_rows(rows, scope=scope)
    payload = summary.model_dump(mode="json")
    row_count = summary.overall.row_count
    return ToolExecutionResult(
        name="summarize_yield",
        arguments=scope.model_dump(mode="json"),
        summary=f"Computed yield summary over {row_count} row(s).",
        result_count=row_count,
        payload=payload,
        sources=[
            AgentSource(
                source_id="prism_yield_records",
                snippet=f"Deterministic yield summary over {row_count} row(s).",
            )
        ],
    )


def _search_prices_impl(
    ctx: ToolExecutionContext,
    *,
    query: str,
    geolocation: str | None = None,
    commodity_type: str | None = None,
    commodity: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    month: str | None = None,
    limit: int = 5,
) -> ToolExecutionResult:
    flt = build_price_filter(
        geolocation=geolocation,
        commodity_type=commodity_type,
        commodity=commodity,
        year_min=year_min,
        year_max=year_max,
        month=month,
    )
    hits = ctx.store.search_prices(query_text=query, flt=flt, limit=limit, min_score=ctx.min_score)
    payloads = [{"score": hit.score, **hit.payload} for hit in hits]
    sources = [_source_from_payload(hit.payload, source_id="openstat_price_knowledge") for hit in hits]
    return ToolExecutionResult(
        name="search_prices",
        arguments={
            "query": query,
            "geolocation": geolocation,
            "commodity_type": commodity_type,
            "commodity": commodity,
            "year_min": year_min,
            "year_max": year_max,
            "month": month,
            "limit": limit,
        },
        summary=f"Found {len(hits)} price knowledge hit(s).",
        result_count=len(hits),
        payload={"hits": payloads},
        sources=sources,
    )


def _summarize_prices_impl(
    ctx: ToolExecutionContext,
    *,
    geolocation: str | None = None,
    commodity_type: str | None = None,
    commodity: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    month: str | None = None,
) -> ToolExecutionResult:
    flt = build_price_filter(
        geolocation=geolocation,
        commodity_type=commodity_type,
        commodity=commodity,
        year_min=year_min,
        year_max=year_max,
        month=month,
    )
    scope = PriceSummaryScope(
        geolocation=geolocation,
        commodity_type=commodity_type,
        commodity=commodity,
        year_min=year_min,
        year_max=year_max,
        month=month,
    )
    rows = list(ctx.store.iter_price_rows(flt))
    summary = aggregate_price_rows(rows, scope=scope)
    payload = summary.model_dump(mode="json")
    row_count = summary.overall.row_count
    return ToolExecutionResult(
        name="summarize_prices",
        arguments=scope.model_dump(mode="json"),
        summary=f"Computed price summary over {row_count} row(s).",
        result_count=row_count,
        payload=payload,
        sources=[
            AgentSource(
                source_id="openstat_price_records",
                snippet=f"Deterministic price summary over {row_count} row(s).",
            )
        ],
    )


def build_agent_tools(ctx: ToolExecutionContext) -> list[BaseTool]:
    return [
        StructuredTool.from_function(
            name="search_corpus",
            description="Search the unified narrative agri corpus for articles, PDFs, and PRiSM browser chunks.",
            args_schema=SearchCorpusArgs,
            func=lambda **kwargs: _search_corpus_impl(ctx, **kwargs),
        ),
        StructuredTool.from_function(
            name="search_yield_knowledge",
            description="Semantic search over textified PRiSM yield knowledge rows.",
            args_schema=SearchYieldKnowledgeArgs,
            func=lambda **kwargs: _search_yield_knowledge_impl(ctx, **kwargs),
        ),
        StructuredTool.from_function(
            name="summarize_yield",
            description="Compute exact deterministic PRiSM yield summary for filters.",
            args_schema=SummarizeYieldArgs,
            func=lambda **kwargs: _summarize_yield_impl(ctx, **kwargs),
        ),
        StructuredTool.from_function(
            name="search_prices",
            description="Semantic search over OpenSTAT farmgate price knowledge rows.",
            args_schema=SearchPricesArgs,
            func=lambda **kwargs: _search_prices_impl(ctx, **kwargs),
        ),
        StructuredTool.from_function(
            name="summarize_prices",
            description="Compute exact deterministic OpenSTAT farmgate price summary for filters.",
            args_schema=SummarizePricesArgs,
            func=lambda **kwargs: _summarize_prices_impl(ctx, **kwargs),
        ),
    ]
