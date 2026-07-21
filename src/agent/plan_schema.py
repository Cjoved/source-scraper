"""Structured plan schema for the LLM Plan-and-Execute agent."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ALLOWED_PLAN_TOOLS = (
    "summarize_prices",
    "search_prices",
    "summarize_yield",
    "search_yield_knowledge",
    "search_corpus",
    "list_openstat_commodities",
    "none",
)

ALLOWED_SOURCE_IDS = frozenset({"philrice_news", "irri", "philrice", "pinoyrice"})

PlanToolName = Literal[
    "summarize_prices",
    "search_prices",
    "summarize_yield",
    "search_yield_knowledge",
    "search_corpus",
    "list_openstat_commodities",
    "none",
]

PrimaryIntent = Literal[
    "price_query",
    "yield_query",
    "metadata_query",
    "news_query",
    "paper_query",
    "advisory_query",
    "unclear_query",
    "developer_task",
    "mixed",
]


class PlanStep(BaseModel):
    tool: PlanToolName
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""


class AgentPlan(BaseModel):
    language: str = "tl"
    goal: str = ""
    steps: list[PlanStep] = Field(default_factory=list, max_length=5)
    needs_clarification: bool = False
    clarification_question: str | None = None
    primary_intent: PrimaryIntent = "unclear_query"


PLANNER_SYSTEM_PROMPT = """You are the planning module for AgriDataAgent (Philippine rice/agri data).

Emit ONE structured plan that lists the read-only tools to run before answering.
Do not answer the user. Do not invent prices, yields, article titles, or URLs.

Available tools:
- summarize_prices: exact farmgate/OpenSTAT price averages (use for magkano/average/presyo)
- search_prices: exploratory price knowledge search
- summarize_yield: exact PRiSM yield averages (use for ani/yield averages)
- search_yield_knowledge: exploratory yield knowledge search
- search_corpus: IRRI / PhilRice news / papers / advisories (use sort_by=latest for latest/recent/pinakabago)
- list_openstat_commodities: list OpenSTAT farmgate commodity types and commodities (use for available crops/data catalog questions)
- none: no retrieval (clarification or chit-chat)

Rules:
- Prefer 1 step; use up to 3 only for compound questions (e.g. price AND news).
- For numeric price/yield questions prefer summarize_* over search_*.
- For news/latest balita use search_corpus with source_ids from [philrice_news, irri] unless user names a source.
- For papers/publications use search_corpus with source_ids [philrice, pinoyrice] unless user names IRRI papers.
- Put commodity as short labels (Palay, Corn, Bigas, Rice) when relevant.
- Put geolocation/province when the user names a place.
- Put year_min/year_max when the user names years or relative dates.
- If price/yield is asked but province/location is missing, set needs_clarification=true, steps=[], and ask one short clarification in the user's language.
- primary_intent=mixed when multiple tool families are needed.
- language: tl for Tagalog/Taglish, en for English.
"""
