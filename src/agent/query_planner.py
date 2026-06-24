"""Deterministic query planning before LLM tool execution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from src.agent.intent import FARMER_CORPUS_SOURCE_IDS, FarmerIntentResult
from src.api.schemas import AgentWarning

ToolPreference = Literal[
    "summarize_prices",
    "search_prices",
    "summarize_yield",
    "search_yield_knowledge",
    "search_corpus",
    "none",
]

_PROVINCE_MARKERS = (
    "Abra",
    "Agusan del Norte",
    "Agusan del Sur",
    "Aklan",
    "Albay",
    "Antique",
    "Apayao",
    "Aurora",
    "Bataan",
    "Batanes",
    "Batangas",
    "Benguet",
    "Biliran",
    "Bohol",
    "Bukidnon",
    "Bulacan",
    "Cagayan",
    "Camarines Norte",
    "Camarines Sur",
    "Camiguin",
    "Capiz",
    "Catanduanes",
    "Cavite",
    "Cebu",
    "Cotabato",
    "Davao de Oro",
    "Davao del Norte",
    "Davao del Sur",
    "Davao Occidental",
    "Davao Oriental",
    "Dinagat Islands",
    "Eastern Samar",
    "Guimaras",
    "Ifugao",
    "Ilocos Norte",
    "Ilocos Sur",
    "Iloilo",
    "Isabela",
    "Kalinga",
    "La Union",
    "Laguna",
    "Lanao del Norte",
    "Lanao del Sur",
    "Leyte",
    "Maguindanao",
    "Marinduque",
    "Masbate",
    "Misamis Occidental",
    "Misamis Oriental",
    "Mountain Province",
    "Negros Occidental",
    "Negros Oriental",
    "Northern Samar",
    "Nueva Ecija",
    "Nueva Vizcaya",
    "Occidental Mindoro",
    "Oriental Mindoro",
    "Palawan",
    "Pampanga",
    "Pangasinan",
    "Quezon",
    "Quirino",
    "Rizal",
    "Romblon",
    "Samar",
    "Sarangani",
    "Siquijor",
    "Sorsogon",
    "South Cotabato",
    "Southern Leyte",
    "Sultan Kudarat",
    "Sulu",
    "Surigao del Norte",
    "Surigao del Sur",
    "Tarlac",
    "Tawi-Tawi",
    "Zambales",
    "Zamboanga del Norte",
    "Zamboanga del Sur",
    "Zamboanga Sibugay",
)


@dataclass(frozen=True)
class DateRange:
    year_min: int | None = None
    year_max: int | None = None
    month: str | None = None


@dataclass(frozen=True)
class AgentQueryPlan:
    intent: str
    tool_preference: ToolPreference
    date_range: DateRange = field(default_factory=DateRange)
    location: str | None = None
    crop: str | None = None
    commodity: str | None = None
    source_ids: list[str] | None = None
    ignored_context: list[str] = field(default_factory=list)
    warnings: list[AgentWarning] = field(default_factory=list)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _explicit_years(message: str) -> list[int]:
    years = [int(match) for match in re.findall(r"(?<!\d)(19\d{2}|20\d{2}|21\d{2})(?!\d)", message)]
    return [year for year in years if 1900 <= year <= 2100]


def resolve_date_range(message: str, *, today: date | None = None) -> DateRange:
    """Resolve common farmer-style date expressions into a year range."""
    current = today or date.today()
    text = message.lower()
    years = _explicit_years(message)
    if len(years) >= 2:
        return DateRange(year_min=min(years[0], years[1]), year_max=max(years[0], years[1]))
    if len(years) == 1:
        return DateRange(year_min=years[0], year_max=years[0])

    years_ago = re.search(r"\b(\d{1,2})\s+years?\s+ago\b", text)
    if years_ago:
        year = current.year - int(years_ago.group(1))
        return DateRange(year_min=year, year_max=year)

    tagalog_years_ago = re.search(r"\b(\d{1,2})\s+taon\s+(?:na\s+)?(?:nakaraan|ang nakalipas)\b", text)
    if tagalog_years_ago:
        year = current.year - int(tagalog_years_ago.group(1))
        return DateRange(year_min=year, year_max=year)

    if _has_any(text, ("last year", "nakaraang taon", "last season")):
        year = current.year - 1
        return DateRange(year_min=year, year_max=year)
    if _has_any(text, ("this year", "ngayon", "current year", "kasalukuyang taon")):
        return DateRange(year_min=current.year, year_max=current.year)
    return DateRange()


def _infer_location(message: str, explicit_location: str | None) -> str | None:
    if explicit_location and explicit_location.strip():
        return explicit_location.strip()
    lowered = message.lower()
    for marker in _PROVINCE_MARKERS:
        if re.search(rf"\b{re.escape(marker.lower())}\b", lowered):
            return marker
    return None


def _commodity_from_crop(crop: str | None) -> str | None:
    if not crop:
        return None
    normalized = crop.lower().strip()
    if normalized in {"palay", "rice", "bigas"}:
        return "Palay"
    if normalized in {"mais", "corn"}:
        return "Corn"
    return crop.strip() or None


def _tool_preference(intent: str, message: str) -> ToolPreference:
    text = message.lower()
    exploratory = _has_any(text, ("hanap", "maghanap", "search", "records", "record"))
    numeric = _has_any(text, ("average", "avg", "mean", "highest", "lowest", "trend", "total", "magkano"))
    if intent == "price_query":
        return "search_prices" if exploratory and not numeric else "summarize_prices"
    if intent == "yield_query":
        return "search_yield_knowledge" if exploratory and not numeric else "summarize_yield"
    if intent in {"news_query", "advisory_query"}:
        return "search_corpus"
    return "none"


def build_query_plan(
    *,
    message: str,
    farmer_context: FarmerIntentResult,
    source_ids: list[str] | None,
    today: date | None = None,
) -> AgentQueryPlan:
    intent = farmer_context.intent
    ignored_context: list[str] = []
    warnings: list[AgentWarning] = []
    plan_source_ids: list[str] | None = None

    if intent in {"news_query", "advisory_query"}:
        plan_source_ids = farmer_context.recommended_source_ids or list(source_ids or FARMER_CORPUS_SOURCE_IDS)
    elif source_ids:
        ignored_context.append("source_ids")
        warnings.append(
            AgentWarning(
                code="source_scope_ignored",
                message="source_ids apply only to corpus/news tools and were ignored for this data query.",
            )
        )

    return AgentQueryPlan(
        intent=intent,
        tool_preference=_tool_preference(intent, message),
        date_range=resolve_date_range(message, today=today),
        location=_infer_location(message, farmer_context.location),
        crop=farmer_context.crop,
        commodity=_commodity_from_crop(farmer_context.crop),
        source_ids=plan_source_ids,
        ignored_context=ignored_context,
        warnings=warnings,
    )


def query_plan_text(plan: AgentQueryPlan) -> str:
    parts = [
        f"intent={plan.intent}",
        f"tool_preference={plan.tool_preference}",
        f"year_min={plan.date_range.year_min or 'not specified'}",
        f"year_max={plan.date_range.year_max or 'not specified'}",
        f"month={plan.date_range.month or 'not specified'}",
        f"location={plan.location or 'not specified'}",
        f"crop={plan.crop or 'not specified'}",
        f"commodity={plan.commodity or 'not specified'}",
        f"source_ids={', '.join(plan.source_ids) if plan.source_ids else 'not applicable'}",
        f"ignored_context={', '.join(plan.ignored_context) if plan.ignored_context else 'none'}",
    ]
    if plan.warnings:
        parts.append("warnings=" + ", ".join(warning.code for warning in plan.warnings))
    return "\n".join(parts)
