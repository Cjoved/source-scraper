"""Read-only LangChain tools for the API agent."""

from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import date
from typing import Any, Literal
from urllib.parse import quote_plus

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from src.api.schemas import AgentSource, PriceSummaryScope, SemesterCode, SummaryScope
from src.services.aggregation import aggregate_rows
from src.services.filters import build_yield_filter
from src.services.price_aggregation import aggregate_price_rows
from src.services.price_filters import build_price_filter
from src.storage.qdrant_store import CorpusFilter, KnowledgeHitRecord, QdrantStoreProtocol

MAX_TOOL_LIMIT = 10
SNIPPET_CHARS = 500
LATEST_CORPUS_SCAN_LIMIT = 5000


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
    sort_by: Literal["relevance", "latest"] = "relevance"


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


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _semester(value: int | None) -> SemesterCode | None:
    return SemesterCode(value) if value in (1, 2) else None


def _fallback_source_url(payload: dict[str, Any]) -> str | None:
    source_id = str(payload.get("source_id") or "").lower()
    title = _string_or_none(payload.get("title"))
    filename = _string_or_none(payload.get("filename"))
    query = title or filename
    if not query:
        return None
    if source_id == "pinoyrice":
        return f"https://www.pinoyrice.com/?s={quote_plus(query)}"
    if source_id == "philrice":
        return f"https://www.philrice.gov.ph/?s={quote_plus(query)}"
    return None


def _source_from_payload(payload: dict[str, Any], *, source_id: str) -> AgentSource:
    url = _string_or_none(payload.get("url") or payload.get("pdf_url") or payload.get("source_url"))
    return AgentSource(
        source_id=_string_or_none(payload.get("source_id")) or source_id,
        title=_string_or_none(payload.get("title")),
        url=url or _fallback_source_url(payload),
        filename=_string_or_none(payload.get("filename")),
        page=_int_or_none(payload.get("page")),
        snippet=_snippet(payload.get("text") or payload),
    )


def _scope_snippet(prefix: str, scope: BaseModel, row_count: int) -> str:
    filters = {
        key: value
        for key, value in scope.model_dump(mode="json").items()
        if value is not None
    }
    suffix = f" Filters: {filters}." if filters else ""
    return _snippet(f"{prefix} over {row_count} row(s).{suffix}")


def _payload_date(payload: dict[str, Any]) -> date | None:
    fields = (
        "date",
        "published_date",
        "published_at",
        "posted",
        "created_at",
        "scraped_at",
        "filename",
        "doc_id",
        "url",
        "title",
        "text",
    )
    for field in fields:
        value = payload.get(field)
        if not value:
            continue
        match = re.search(
            r"(?<!\d)(20\d{2}|19\d{2})[-_/](0[1-9]|1[0-2])[-_/]([0-2]\d|3[01])(?!\d)",
            str(value),
        )
        if not match:
            continue
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
    return None


def _news_requested(query: str) -> bool:
    text = query.lower()
    markers = ("news", "balita", "update")
    return any(marker in text for marker in markers)


def _papers_requested(query: str) -> bool:
    text = query.lower()
    markers = (
        "paper",
        "papers",
        "publication",
        "publications",
        "research",
        "study",
        "studies",
        "journal",
        "pdf",
        "document",
        "dokumento",
        "babasan",
        "babasahin",
    )
    return any(marker in text for marker in markers)


def _news_like_payload(payload: dict[str, Any]) -> bool:
    source_id = str(payload.get("source_id") or "").lower()
    if source_id == "philrice_news":
        return True
    if payload.get("page") is not None:
        return False
    searchable = " ".join(
        str(payload.get(field) or "").lower()
        for field in ("url", "filename", "doc_id", "title")
    )
    if ".pdf" in searchable:
        return False
    if "news" in searchable:
        return True
    return source_id == "irri"


def _paper_like_payload(payload: dict[str, Any]) -> bool:
    source_id = str(payload.get("source_id") or "").lower()
    if source_id in {"philrice", "pinoyrice"}:
        return True
    searchable = " ".join(
        str(payload.get(field) or "").lower()
        for field in ("url", "filename", "doc_id", "title")
    )
    markers = ("paper", "publication", "research", "study", "journal", ".pdf")
    return any(marker in searchable for marker in markers)


def _sort_corpus_hits(hits: list[Any], sort_by: str) -> list[Any]:
    if sort_by != "latest":
        return hits
    return sorted(
        hits,
        key=lambda hit: (
            _payload_date(hit.payload) is not None,
            _payload_date(hit.payload) or date.min,
            hit.score,
        ),
        reverse=True,
    )


def _corpus_document_key(payload: dict[str, Any]) -> tuple[str, str]:
    source_id = str(payload.get("source_id") or "").strip().lower()
    for field in ("title", "url", "pdf_url", "source_url", "doc_id", "filename"):
        value = str(payload.get(field) or "").strip().lower()
        if value:
            return source_id, value
    return source_id, _snippet(payload)


def _dedupe_corpus_documents(hits: list[KnowledgeHitRecord]) -> list[KnowledgeHitRecord]:
    seen: set[tuple[str, str]] = set()
    deduped: list[KnowledgeHitRecord] = []
    for hit in hits:
        key = _corpus_document_key(hit.payload)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return deduped


def _latest_corpus_hits(
    ctx: ToolExecutionContext,
    *,
    query: str,
    flt: CorpusFilter,
    limit: int,
) -> list[KnowledgeHitRecord]:
    candidates: list[KnowledgeHitRecord] = []
    news_requested = _news_requested(query)
    papers_requested = _papers_requested(query)
    for payload in ctx.store.iter_corpus_rows(flt, max_rows=LATEST_CORPUS_SCAN_LIMIT):
        if _payload_date(payload) is None:
            continue
        if news_requested and not _news_like_payload(payload):
            continue
        if papers_requested and not _paper_like_payload(payload):
            continue
        candidates.append(KnowledgeHitRecord(score=1.0, payload=payload))
    return _dedupe_corpus_documents(_sort_corpus_hits(candidates, "latest"))[:limit]


def _search_corpus_impl(
    ctx: ToolExecutionContext,
    *,
    query: str,
    source_ids: list[str] | None = None,
    limit: int = 5,
    sort_by: Literal["relevance", "latest"] = "relevance",
) -> ToolExecutionResult:
    flt = CorpusFilter(source_ids=tuple(source_ids) if source_ids else None)
    if sort_by == "latest":
        hits = _latest_corpus_hits(ctx, query=query, flt=flt, limit=limit)
    else:
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
        arguments={"query": query, "source_ids": source_ids, "limit": limit, "sort_by": sort_by},
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
    sources = [
        AgentSource(
            source_id="prism_yield_records",
            snippet=_scope_snippet("Deterministic yield summary", scope, row_count),
        )
    ] if row_count else []
    return ToolExecutionResult(
        name="summarize_yield",
        arguments=scope.model_dump(mode="json"),
        summary=f"Computed yield summary over {row_count} row(s).",
        result_count=row_count,
        payload=payload,
        sources=sources,
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
    sources = [
        AgentSource(
            source_id="openstat_price_records",
            snippet=_scope_snippet("Deterministic price summary", scope, row_count),
        )
    ] if row_count else []
    return ToolExecutionResult(
        name="summarize_prices",
        arguments=scope.model_dump(mode="json"),
        summary=f"Computed price summary over {row_count} row(s).",
        result_count=row_count,
        payload=payload,
        sources=sources,
    )


def build_agent_tools(ctx: ToolExecutionContext) -> list[BaseTool]:
    return [
        StructuredTool.from_function(
            name="search_corpus",
            description=(
                "Search the unified narrative agri corpus for articles, PDFs, and PRiSM browser chunks. "
                "Use sort_by='latest' when the user asks for latest, newest, recent, or pinakabagong news."
            ),
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
