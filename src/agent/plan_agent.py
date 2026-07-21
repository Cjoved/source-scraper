"""Dedicated search plan agent: route tools and rewrite corpus queries before retrieval."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agent.intent import (
    FARMER_CORPUS_SOURCE_IDS,
    FARMER_NEWS_SOURCE_IDS,
    FARMER_PAPER_SOURCE_IDS,
    FarmerIntent,
    FarmerIntentResult,
    _infer_crop,
)
from src.agent.plan_schema import (
    ALLOWED_PLAN_TOOLS,
    ALLOWED_SOURCE_IDS,
    PLANNER_SYSTEM_PROMPT,
    AgentPlan,
    PlanStep,
)
from src.agent.follow_up import looks_like_data_continuation
from src.agent.query_planner import (
    AgentQueryPlan,
    DateRange,
    ToolPreference,
    _commodity_from_crop,
    _infer_location,
    resolve_date_range,
)
from src.agent.tools import ToolExecutionResult
from src.api.schemas import AgentSessionState, AgentSource, AgentWarning

_FILLER_PATTERNS = (
    r"\bano\b",
    r"\bang\b",
    r"\ba\b",
    r"\bthe\b",
    r"\bngayon\b",
    r"\bngayong\b",
    r"\btayo\b",
    r"\bnatin\b",
    r"\bba\b",
    r"\bpo\b",
    r"\bplease\b",
    r"\bkung\b",
    r"\bmeron\b",
    r"\bmay\b",
    r"\bwala\b",
    r"\bigay\b",
    r"\bsabi\b",
    r"\blang\b",
    r"\bmga\b",
    r"\byung\b",
    r"\btungkol\b",
    r"\bsa\b",
    r"\bna\b",
    r"\bpara\b",
    r"\bmo\b",
    r"\bko\b",
    r"\bninyo\b",
)

_TOPIC_MAP = (
    (("climate", "klima", "init", "tag-ulan", "tagulan"), "climate"),
    (("pest", "peste", "insect", "worm", "uod"), "pest"),
    (("disease", "sakit", "blight", "tungro"), "disease"),
    (("fertilizer", "pataba", "abon"), "fertilizer"),
    (("irrigation", "patubig", "tubig"), "irrigation"),
    (("seed", "binhi", "variety", "uri"), "seeds"),
    (("harvest", "ani", "yield"), "harvest yield"),
    (("price", "presyo", "farmgate"), "price"),
    (("palay", "rice", "bigas"), "rice"),
    (("mais", "corn"), "corn"),
)


class CorpusRewriteOutput(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=5)
    rationale: str = ""


@dataclass
class SearchPlan:
    intent: str
    tool_name: str
    tool_args: dict[str, Any]
    search_queries: list[str]
    source_ids: list[str] | None
    skip_retrieval: bool
    query_plan: AgentQueryPlan
    farmer_context: FarmerIntentResult
    warnings: list[AgentWarning] = field(default_factory=list)
    allow_cascade_escalate: bool = True
    cascade_max_queries: int = 3


@dataclass
class ValidatedAgentPlan:
    """Normalized multi-step plan ready for orchestrator execution."""

    primary_intent: str
    language: str
    goal: str
    needs_clarification: bool
    clarification_question: str | None
    skip_retrieval: bool
    search_plans: list[SearchPlan]
    query_plan: AgentQueryPlan
    farmer_context: FarmerIntentResult
    planned_tool_names: frozenset[str]
    warnings: list[AgentWarning] = field(default_factory=list)
    allow_cascade_escalate: bool = True
    cascade_max_queries: int = 3


_LISTING_FILLERS = frozenset(
    {
        "latest",
        "newest",
        "recent",
        "news",
        "balita",
        "agri",
        "agriculture",
        "rice",
        "palay",
        "irri",
        "philrice",
        "update",
        "updates",
        "paper",
        "papers",
        "publication",
        "publications",
        "ano",
        "anong",
        "ang",
        "alin",
        "saan",
        "bakit",
        "paano",
        "what",
        "which",
        "when",
        "where",
        "why",
        "how",
        "find",
        "check",
        "tingnan",
        "meron",
        "may",
        "ngayon",
        "ngayong",
        "please",
    }
)


def is_vague_listing_query(message: str, search_query: str) -> bool:
    """True when the ask is mostly 'latest news' without a concrete topic."""
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", f"{message} {search_query}".lower())
        if len(token) > 2
    ]
    if not tokens:
        return True
    topical = [token for token in tokens if token not in _LISTING_FILLERS]
    return len(topical) == 0


def is_weak_corpus_result(
    result: ToolExecutionResult,
    *,
    min_score: float,
    limit: int,
    message: str,
    search_query: str,
    sort_by: str | None,
) -> bool:
    """Stage-1 weakness checks used to decide Stage-2 escalate."""
    if sort_by == "latest":
        # Latest listing is date-ordered; only escalate on empty results.
        return result.result_count == 0
    if result.result_count == 0:
        return True
    hits = result.payload.get("hits") if isinstance(result.payload, dict) else None
    if not isinstance(hits, list) or not hits:
        return True
    first = hits[0] if isinstance(hits[0], dict) else {}
    try:
        top_score = float(first.get("score") or 0.0)
    except (TypeError, ValueError):
        top_score = 0.0
    if top_score < min_score:
        return True
    if is_vague_listing_query(message, search_query) and result.result_count < limit:
        return True
    return False


def rerank_merged_corpus_result(
    result: ToolExecutionResult,
    *,
    query: str,
    limit: int,
    enabled: bool,
) -> ToolExecutionResult:
    """Rerank merged multi-query corpus hits against the primary query."""
    if not enabled or result.name != "search_corpus":
        return result
    hits = result.payload.get("hits") if isinstance(result.payload, dict) else None
    if not isinstance(hits, list) or not hits:
        return result
    from src.services.rerank import candidate_text, rerank_texts
    from src.storage.qdrant_store import KnowledgeHitRecord

    records = [
        KnowledgeHitRecord(
            score=float(hit.get("score") or 0.0) if isinstance(hit, dict) else 0.0,
            payload={k: v for k, v in hit.items() if k != "score"} if isinstance(hit, dict) else {},
        )
        for hit in hits
        if isinstance(hit, dict)
    ]
    candidates = [
        {"text": candidate_text(record.payload), "score": record.score} for record in records
    ]
    ranked = rerank_texts(query, candidates, top_k=limit, enabled=True)
    ordered_hits = []
    ordered_sources: list[AgentSource] = []
    for index, score in zip(ranked.ordered_indexes, ranked.scores, strict=False):
        record = records[index]
        payload = dict(record.payload)
        payload["score"] = float(score)
        ordered_hits.append(payload)
        if index < len(result.sources):
            ordered_sources.append(result.sources[index])
        else:
            ordered_sources.append(
                AgentSource(
                    source_id=str(payload.get("source_id") or "agri_corpus_rag"),
                    title=str(payload.get("title") or "") or None,
                    url=str(payload.get("url") or payload.get("pdf_url") or "") or None,
                    filename=str(payload.get("filename") or "") or None,
                    snippet=str(payload.get("text") or "")[:500] or None,
                )
            )
    arguments = dict(result.arguments)
    arguments["limit"] = limit
    return ToolExecutionResult(
        name=result.name,
        arguments=arguments,
        summary=f"Found {len(ordered_hits)} corpus hit(s) after cascade merge+rerank.",
        result_count=len(ordered_hits),
        payload={
            **(result.payload if isinstance(result.payload, dict) else {}),
            "hits": ordered_hits,
        },
        sources=ordered_sources,
    )


def latest_requested(message: str) -> bool:
    text = message.lower()
    markers = (
        "latest",
        "newest",
        "recent",
        "pinakabago",
        "pinaka bago",
        "bagong balita",
        "latest news",
        "pinakabagong",
    )
    return any(marker in text for marker in markers)


def build_forced_tool_args(
    *,
    tool_name: str,
    message: str,
    query_plan: AgentQueryPlan,
    search_query: str | None = None,
) -> dict[str, Any]:
    """Build ready-to-invoke tool arguments from the query plan."""
    args: dict[str, Any] = {}
    if tool_name == "search_corpus":
        args["query"] = (search_query or message).strip() or message
        if query_plan.source_ids:
            args["source_ids"] = list(query_plan.source_ids)
        if latest_requested(message):
            args["sort_by"] = "latest"
        return args

    if tool_name in {"search_prices", "summarize_prices"}:
        if query_plan.location:
            args["geolocation"] = query_plan.location
        if query_plan.commodity:
            args["commodity"] = query_plan.commodity
        if query_plan.date_range.year_min is not None:
            args["year_min"] = query_plan.date_range.year_min
        if query_plan.date_range.year_max is not None:
            args["year_max"] = query_plan.date_range.year_max
        if query_plan.date_range.month:
            args["month"] = query_plan.date_range.month
        if tool_name == "search_prices":
            args["query"] = (search_query or message).strip() or message
        return args

    if tool_name in {"search_yield_knowledge", "summarize_yield"}:
        if query_plan.location:
            args["province"] = query_plan.location
        if query_plan.date_range.year_min is not None:
            args["year_min"] = query_plan.date_range.year_min
        if query_plan.date_range.year_max is not None:
            args["year_max"] = query_plan.date_range.year_max
        if tool_name == "search_yield_knowledge":
            args["query"] = (search_query or message).strip() or message
        return args

    if tool_name == "list_openstat_commodities":
        return args

    return args


def normalize_tool_args_with_plan(
    name: str,
    args: dict[str, Any],
    *,
    message: str,
    query_plan: AgentQueryPlan,
) -> dict[str, Any]:
    """Overlay plan filters onto model-requested tool args (follow-up calls)."""
    normalized = dict(args)
    if name == "search_corpus":
        if query_plan.source_ids:
            normalized["source_ids"] = list(query_plan.source_ids)
        if latest_requested(message) and not normalized.get("sort_by"):
            normalized["sort_by"] = "latest"
    if name in {"search_prices", "summarize_prices"}:
        if query_plan.location:
            normalized["geolocation"] = query_plan.location
        if query_plan.commodity:
            normalized["commodity"] = query_plan.commodity
        if query_plan.date_range.year_min is not None:
            normalized["year_min"] = query_plan.date_range.year_min
        if query_plan.date_range.year_max is not None:
            normalized["year_max"] = query_plan.date_range.year_max
        if query_plan.date_range.month:
            normalized["month"] = query_plan.date_range.month
        if name == "search_prices" and not normalized.get("query"):
            normalized["query"] = message
    if name in {"search_yield_knowledge", "summarize_yield"}:
        if query_plan.location and not any(
            normalized.get(key) for key in ("region", "province", "municipality")
        ):
            normalized["province"] = query_plan.location
        if query_plan.date_range.year_min is not None:
            normalized["year_min"] = query_plan.date_range.year_min
        if query_plan.date_range.year_max is not None:
            normalized["year_max"] = query_plan.date_range.year_max
        if name == "search_yield_knowledge" and not normalized.get("query"):
            normalized["query"] = message
    if name == "list_openstat_commodities":
        return normalized
    return normalized


def _should_skip_retrieval(
    farmer_context: FarmerIntentResult,
    query_plan: AgentQueryPlan,
    *,
    message: str = "",
    session: AgentSessionState | None = None,
) -> bool:
    if farmer_context.intent == "unclear_query":
        return True
    if farmer_context.intent in {"price_query", "yield_query"}:
        if query_plan.location:
            return False
        if session and session.location:
            return False
        if (
            session
            and session.last_tool_name
            and looks_like_data_continuation(message, session)
            and session.last_tool_name in {"summarize_prices", "search_prices", "summarize_yield", "search_yield_knowledge"}
        ):
            return False
        return True
    return False


def _strip_filler(message: str) -> str:
    text = message.lower()
    text = re.sub(r"[^\w\s\-]", " ", text, flags=re.UNICODE)
    for pattern in _FILLER_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _topic_keywords(message: str) -> list[str]:
    lowered = message.lower()
    found: list[str] = []
    for markers, label in _TOPIC_MAP:
        if any(marker in lowered for marker in markers):
            found.append(label)
    return found


def deterministic_corpus_query(
    message: str,
    *,
    query_plan: AgentQueryPlan,
    farmer_context: FarmerIntentResult,
) -> str:
    """Rewrite Taglish/filler user text into a retrieval-friendly corpus query."""
    parts: list[str] = []
    source_ids = query_plan.source_ids or farmer_context.recommended_source_ids or []

    if query_plan.intent == "news_query" or latest_requested(message):
        parts.append("latest")
    if query_plan.intent == "paper_query":
        parts.append("research paper publication")
    elif query_plan.intent == "news_query":
        parts.append("agriculture rice news")
    elif query_plan.intent == "advisory_query":
        parts.append("farmer advisory guide")

    if "irri" in source_ids and len(source_ids) == 1:
        parts.append("IRRI")
    elif "philrice_news" in source_ids and "irri" not in source_ids:
        parts.append("PhilRice news")
    elif "philrice" in source_ids and query_plan.intent == "paper_query":
        parts.append("PhilRice")
    elif "pinoyrice" in source_ids and query_plan.intent == "paper_query":
        parts.append("PinoyRice")

    parts.extend(_topic_keywords(message))
    if farmer_context.crop and farmer_context.crop.lower() not in {" ".join(parts).lower()}:
        parts.append(farmer_context.crop)

    cleaned = _strip_filler(message)
    # Keep meaningful leftover tokens (length > 2) not already covered.
    covered = " ".join(parts).lower()
    for token in cleaned.split():
        if len(token) <= 2:
            continue
        if token in covered:
            continue
        if token in {"news", "balita", "paper", "papers", "latest", "agri", "agriculture"}:
            continue
        parts.append(token)

    query = re.sub(r"\s+", " ", " ".join(parts)).strip()
    return query or "rice agriculture"


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text


def rewrite_corpus_queries_with_llm(
    model: Any,
    *,
    message: str,
    query_plan: AgentQueryPlan,
    farmer_context: FarmerIntentResult,
    primary_query: str,
    max_queries: int,
) -> list[str] | None:
    """Optional structured multi-query rewrite. Returns None on failure (fail open)."""
    payload = {
        "user_message": message,
        "intent": query_plan.intent,
        "source_ids": query_plan.source_ids,
        "crop": farmer_context.crop,
        "location": query_plan.location,
        "primary_query": primary_query,
        "max_queries": max_queries,
    }
    try:
        response = model.invoke(
            [
                SystemMessage(
                    content=(
                        "You rewrite farmer agri questions into short retrieval queries for a "
                        "Philippine rice/agri corpus (IRRI, PhilRice news, PhilRice papers, PinoyRice). "
                        "Return only strict JSON: "
                        '{"queries":["..."],"rationale":"short"}. '
                        "Rules: do not invent facts or article titles; keep entities; "
                        "use English and/or Tagalog keywords that match news/PDF text; "
                        f"return 1 to {max_queries} queries."
                    )
                ),
                HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
            ]
        )
        raw = _content_to_text(getattr(response, "content", response))
        data = json.loads(_strip_code_fence(raw))
        parsed = CorpusRewriteOutput.model_validate(data)
    except Exception:
        return None

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in parsed.queries:
        query = re.sub(r"\s+", " ", str(item)).strip()
        if not query:
            continue
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(query)
        if len(cleaned) >= max_queries:
            break
    return cleaned or None


def _dedupe_queries(queries: list[str], *, max_queries: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for query in queries:
        cleaned = re.sub(r"\s+", " ", query).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= max_queries:
            break
    return out


def _warning(code: str, message: str) -> AgentWarning:
    return AgentWarning(code=code, message=message)


def _clamp_source_ids(raw: object) -> list[str] | None:
    if raw is None:
        return None
    values: list[str] = []
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",") if item.strip()]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(item).strip() for item in raw if str(item).strip()]
    else:
        return None
    clamped = [item for item in values if item in ALLOWED_SOURCE_IDS]
    # Preserve order, drop dupes.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in clamped:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered or None


def _default_source_ids_for_intent(
    intent: str,
    *,
    body_source_ids: list[str] | None,
) -> list[str] | None:
    clamped_body = _clamp_source_ids(body_source_ids)
    if clamped_body:
        return clamped_body
    if intent == "news_query":
        return list(FARMER_NEWS_SOURCE_IDS)
    if intent == "paper_query":
        return list(FARMER_PAPER_SOURCE_IDS)
    if intent in {"advisory_query", "mixed"}:
        return list(FARMER_CORPUS_SOURCE_IDS)
    return None


def _coerce_primary_intent(value: str) -> FarmerIntent:
    allowed: set[str] = {
        "price_query",
        "yield_query",
        "metadata_query",
        "news_query",
        "paper_query",
        "advisory_query",
        "unclear_query",
        "developer_task",
        "mixed",
    }
    return value if value in allowed else "unclear_query"  # type: ignore[return-value]


def _tool_preference_from_steps(steps: list[PlanStep]) -> ToolPreference:
    for step in steps:
        if step.tool != "none" and step.tool in ALLOWED_PLAN_TOOLS:
            return step.tool  # type: ignore[return-value]
    return "none"


def _as_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_step_args(
    step: PlanStep,
    *,
    message: str,
    location: str | None,
    commodity: str | None,
    date_range: DateRange,
    source_ids: list[str] | None,
    query_plan: AgentQueryPlan,
    farmer_context: FarmerIntentResult,
) -> dict[str, Any]:
    args = dict(step.args or {})
    tool = step.tool

    if tool in {"search_prices", "summarize_prices"}:
        if not args.get("geolocation") and location:
            args["geolocation"] = location
        if not args.get("commodity") and commodity:
            args["commodity"] = commodity
        if args.get("year_min") is None and date_range.year_min is not None:
            args["year_min"] = date_range.year_min
        if args.get("year_max") is None and date_range.year_max is not None:
            args["year_max"] = date_range.year_max
        if not args.get("month") and date_range.month:
            args["month"] = date_range.month
        if tool == "search_prices" and not args.get("query"):
            args["query"] = message
        return args

    if tool in {"search_yield_knowledge", "summarize_yield"}:
        has_place = any(args.get(key) for key in ("region", "province", "municipality"))
        if not has_place and location:
            args["province"] = location
        if args.get("year_min") is None and date_range.year_min is not None:
            args["year_min"] = date_range.year_min
        if args.get("year_max") is None and date_range.year_max is not None:
            args["year_max"] = date_range.year_max
        if tool == "search_yield_knowledge" and not args.get("query"):
            args["query"] = message
        return args

    if tool == "search_corpus":
        clamped = _clamp_source_ids(args.get("source_ids")) or source_ids
        if clamped:
            args["source_ids"] = list(clamped)
        if latest_requested(message) and not args.get("sort_by"):
            args["sort_by"] = "latest"
        query = str(args.get("query") or "").strip()
        if not query:
            query = deterministic_corpus_query(
                message,
                query_plan=query_plan,
                farmer_context=farmer_context,
            )
            args["query"] = query
        return args

    if tool == "list_openstat_commodities":
        return args

    return args


def llm_build_agent_plan(
    model: Any,
    *,
    message: str,
    location: str | None = None,
    crop: str | None = None,
    language: str | None = None,
    source_ids: list[str] | None = None,
    max_steps: int = 3,
) -> AgentPlan | None:
    """Ask the LLM for a structured AgentPlan. Returns None on failure (fail-open)."""
    payload = {
        "user_message": message,
        "location_hint": location,
        "crop_hint": crop,
        "language_hint": language,
        "source_ids_hint": source_ids,
        "max_steps": max_steps,
    }
    messages = [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
    ]

    structured = getattr(model, "with_structured_output", None)
    if callable(structured):
        try:
            planner = structured(AgentPlan)
            response = planner.invoke(messages)
            if isinstance(response, AgentPlan):
                return response
            return AgentPlan.model_validate(response)
        except Exception:
            pass

    try:
        response = model.invoke(messages)
        raw = _content_to_text(getattr(response, "content", response))
        data = json.loads(_strip_code_fence(raw))
        return AgentPlan.model_validate(data)
    except Exception:
        return None


def validate_agent_plan(
    plan: AgentPlan,
    *,
    message: str,
    location: str | None = None,
    crop: str | None = None,
    language: str | None = None,
    source_ids: list[str] | None = None,
    user_type: str = "farmer",
    max_steps: int = 3,
    plan_rewrite: bool = True,
    plan_max_queries: int = 3,
) -> ValidatedAgentPlan:
    """Deterministically normalize/clamp an LLM plan before tool execution."""
    warnings: list[AgentWarning] = []
    primary_intent = _coerce_primary_intent(plan.primary_intent)
    resolved_location = _infer_location(message, location)
    resolved_crop = _infer_crop(message, crop)
    commodity = _commodity_from_crop(resolved_crop)
    date_range = resolve_date_range(message)
    resolved_language = (plan.language or language or "tl").strip() or "tl"

    raw_steps = [step for step in plan.steps if step.tool in ALLOWED_PLAN_TOOLS and step.tool != "none"]
    if len(plan.steps) > max_steps:
        warnings.append(
            _warning(
                "plan_steps_clamped",
                f"Plan steps clamped from {len(plan.steps)} to {max_steps}.",
            )
        )
    raw_steps = raw_steps[:max_steps]

    default_sources = _default_source_ids_for_intent(primary_intent, body_source_ids=source_ids)
    tool_preference = _tool_preference_from_steps(
        [PlanStep(tool=step.tool, args=step.args, rationale=step.rationale) for step in raw_steps]
    )

    clarification = plan.clarification_question
    needs_clarification = bool(plan.needs_clarification)
    price_or_yield_tools = {
        "summarize_prices",
        "search_prices",
        "summarize_yield",
        "search_yield_knowledge",
    }
    uses_price_yield = any(step.tool in price_or_yield_tools for step in raw_steps)
    if uses_price_yield and not resolved_location:
        needs_clarification = True
        if not clarification:
            clarification = (
                "Saang province o lugar mo gustong tingnan ang datos?"
                if resolved_language.lower().startswith(("tl", "fil", "tag"))
                else "Which province or location should I use?"
            )
    if primary_intent == "unclear_query" and not raw_steps:
        needs_clarification = True
        if not clarification:
            clarification = "Ano ang gusto mong malaman: presyo, ani, balita, o problema sa tanim?"

    skip_retrieval = needs_clarification or not raw_steps

    farmer_context = FarmerIntentResult(
        intent=primary_intent,
        user_type=(user_type or "farmer").lower(),
        language=resolved_language,
        location=resolved_location,
        crop=resolved_crop,
        missing_context=needs_clarification,
        clarification_question=clarification if needs_clarification else None,
        recommended_source_ids=default_sources,
    )
    query_plan = AgentQueryPlan(
        intent=primary_intent,
        tool_preference=tool_preference,
        date_range=date_range,
        location=resolved_location,
        crop=resolved_crop,
        commodity=commodity,
        source_ids=default_sources,
        ignored_context=[],
        warnings=[],
    )

    search_plans: list[SearchPlan] = []
    planned_names: list[str] = []
    if not skip_retrieval:
        for step in raw_steps:
            args = _normalize_step_args(
                step,
                message=message,
                location=resolved_location,
                commodity=commodity,
                date_range=date_range,
                source_ids=default_sources,
                query_plan=query_plan,
                farmer_context=farmer_context,
            )
            # Drop unknown year junk / coerce ints
            for key in ("year_min", "year_max"):
                if key in args:
                    coerced = _as_int(args.get(key))
                    if coerced is None:
                        args.pop(key, None)
                    else:
                        args[key] = coerced
            search_queries: list[str] = []
            if step.tool == "search_corpus":
                search_queries = [str(args.get("query") or message)]
            elif step.tool in {"search_prices", "search_yield_knowledge"}:
                search_queries = [str(args.get("query") or message)]
            planned_names.append(step.tool)
            search_plans.append(
                SearchPlan(
                    intent=primary_intent,
                    tool_name=step.tool,
                    tool_args=args,
                    search_queries=search_queries,
                    source_ids=_clamp_source_ids(args.get("source_ids")) or default_sources,
                    skip_retrieval=False,
                    query_plan=query_plan,
                    farmer_context=farmer_context,
                    warnings=[],
                    allow_cascade_escalate=plan_rewrite,
                    cascade_max_queries=plan_max_queries,
                )
            )

    return ValidatedAgentPlan(
        primary_intent=primary_intent,
        language=resolved_language,
        goal=(plan.goal or "").strip(),
        needs_clarification=needs_clarification,
        clarification_question=farmer_context.clarification_question,
        skip_retrieval=skip_retrieval,
        search_plans=search_plans,
        query_plan=query_plan,
        farmer_context=farmer_context,
        planned_tool_names=frozenset(planned_names),
        warnings=warnings,
        allow_cascade_escalate=plan_rewrite,
        cascade_max_queries=plan_max_queries,
    )


def validated_plan_from_search_plan(search_plan: SearchPlan) -> ValidatedAgentPlan:
    """Wrap a legacy keyword SearchPlan as a ValidatedAgentPlan."""
    planned = frozenset() if search_plan.tool_name == "none" else frozenset({search_plan.tool_name})
    return ValidatedAgentPlan(
        primary_intent=search_plan.intent,
        language=search_plan.farmer_context.language,
        goal="",
        needs_clarification=bool(search_plan.farmer_context.clarification_question),
        clarification_question=search_plan.farmer_context.clarification_question,
        skip_retrieval=search_plan.skip_retrieval or search_plan.tool_name == "none",
        search_plans=[] if search_plan.skip_retrieval or search_plan.tool_name == "none" else [search_plan],
        query_plan=search_plan.query_plan,
        farmer_context=search_plan.farmer_context,
        planned_tool_names=planned,
        warnings=list(search_plan.warnings),
        allow_cascade_escalate=search_plan.allow_cascade_escalate,
        cascade_max_queries=search_plan.cascade_max_queries,
    )


def build_search_plan(
    *,
    message: str,
    farmer_context: FarmerIntentResult,
    query_plan: AgentQueryPlan,
    plan_rewrite: bool = True,
    plan_max_queries: int = 3,
    model: Any | None = None,
    session: AgentSessionState | None = None,
) -> SearchPlan:
    """Build an executable search plan (forced tool + args + corpus queries).

    ``plan_rewrite`` allows Stage-2 LLM multi-query escalation after weak Stage-1
    retrieval (handled by the orchestrator). Plans themselves always start with a
    single deterministic corpus query.
    """
    del model  # Stage-2 rewrite runs after retrieval, not during planning.
    warnings = list(query_plan.warnings)
    tool_name = query_plan.tool_preference if query_plan.tool_preference != "none" else "none"
    skip = _should_skip_retrieval(
        farmer_context,
        query_plan,
        message=message,
        session=session,
    )
    if skip:
        tool_name = "none"

    search_queries: list[str] = []
    if tool_name == "search_corpus":
        primary = deterministic_corpus_query(
            message,
            query_plan=query_plan,
            farmer_context=farmer_context,
        )
        search_queries = [primary]
        tool_args = build_forced_tool_args(
            tool_name=tool_name,
            message=message,
            query_plan=query_plan,
            search_query=primary,
        )
    elif tool_name != "none":
        tool_args = build_forced_tool_args(
            tool_name=tool_name,
            message=message,
            query_plan=query_plan,
        )
        if tool_name in {"search_prices", "search_yield_knowledge"}:
            search_queries = [str(tool_args.get("query") or message)]
    else:
        tool_args = {}

    return SearchPlan(
        intent=query_plan.intent,
        tool_name=tool_name,
        tool_args=tool_args,
        search_queries=search_queries,
        source_ids=list(query_plan.source_ids) if query_plan.source_ids else None,
        skip_retrieval=skip,
        query_plan=query_plan,
        farmer_context=farmer_context,
        warnings=warnings,
        allow_cascade_escalate=plan_rewrite,
        cascade_max_queries=plan_max_queries,
    )


def _hit_dedupe_key(payload: dict[str, Any], source: AgentSource | None = None) -> tuple[str, str]:
    source_id = str(
        (source.source_id if source else None) or payload.get("source_id") or ""
    ).strip().lower()
    for field_name in ("url", "pdf_url", "source_url", "doc_id", "filename"):
        value = payload.get(field_name)
        if isinstance(value, str) and value.strip():
            return source_id, value.strip().lower()
    if source is not None:
        if source.url:
            return source_id, source.url.strip().lower()
        if source.filename:
            return source_id, source.filename.strip().lower()
        if source.title:
            return source_id, source.title.strip().lower()
    snippet = str(payload.get("text") or payload.get("snippet") or "")[:120].strip().lower()
    return source_id, snippet


def merge_corpus_results_rrf(
    results: list[ToolExecutionResult],
    *,
    limit: int = 5,
    k: int = 60,
) -> ToolExecutionResult:
    """Merge multi-query corpus tool results with Reciprocal Rank Fusion + dedupe."""
    if not results:
        raise ValueError("merge_corpus_results_rrf requires at least one result")
    if len(results) == 1:
        return results[0]

    scores: dict[tuple[str, str], float] = {}
    best_hit: dict[tuple[str, str], dict[str, Any]] = {}
    best_source: dict[tuple[str, str], AgentSource] = {}
    queries: list[str] = []

    for result in results:
        query = str(result.arguments.get("query") or "")
        if query:
            queries.append(query)
        hits = result.payload.get("hits") if isinstance(result.payload, dict) else None
        hit_list = hits if isinstance(hits, list) else []
        sources = list(result.sources)
        for rank, raw_hit in enumerate(hit_list):
            if not isinstance(raw_hit, dict):
                continue
            source = sources[rank] if rank < len(sources) else None
            key = _hit_dedupe_key(raw_hit, source)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
            previous = best_hit.get(key)
            prev_score = float(previous.get("score") or 0.0) if previous else -1.0
            cur_score = float(raw_hit.get("score") or 0.0)
            if previous is None or cur_score >= prev_score:
                best_hit[key] = dict(raw_hit)
                if source is not None:
                    best_source[key] = source

    ranked_keys = sorted(scores.keys(), key=lambda item: scores[item], reverse=True)[:limit]
    merged_hits: list[dict[str, Any]] = []
    merged_sources: list[AgentSource] = []
    for key in ranked_keys:
        hit = dict(best_hit[key])
        hit["score"] = scores[key]
        merged_hits.append(hit)
        if key in best_source:
            merged_sources.append(best_source[key])

    primary = results[0]
    arguments = dict(primary.arguments)
    arguments["query"] = queries[0] if queries else arguments.get("query")
    arguments["queries"] = queries
    return ToolExecutionResult(
        name="search_corpus",
        arguments=arguments,
        summary=f"Found {len(merged_hits)} corpus hit(s) after multi-query merge.",
        result_count=len(merged_hits),
        payload={"hits": merged_hits, "queries": queries},
        sources=merged_sources,
    )
