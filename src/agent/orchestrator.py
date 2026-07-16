"""Phase 2 LangChain agent orchestration."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from src.agent.client import AgentClientError, create_chat_model
from src.agent.intent import FarmerIntentResult, infer_farmer_intent
from src.agent.prompts import build_agent_messages
from src.agent.query_planner import AgentQueryPlan, build_query_plan, query_plan_text
from src.agent.tools import ToolExecutionContext, ToolExecutionResult, build_agent_tools
from src.api.schemas import (
    AgentConfidence,
    AgentChatRequest,
    AgentChatResponse,
    AgentMode,
    AgentSource,
    AgentTask,
    AgentToolCall,
    AgentWarning,
)
from src.api.settings import Settings
from src.storage.qdrant_store import QdrantStoreProtocol

if TYPE_CHECKING:
    from src.api.auth import AuthScope, CurrentUser


DETERMINISTIC_TOOLS = {"summarize_yield", "summarize_prices"}
SEARCH_TOOLS = {"search_corpus", "search_yield_knowledge", "search_prices"}
PRICE_TOOLS = {"summarize_prices", "search_prices"}
YIELD_TOOLS = {"summarize_yield", "search_yield_knowledge"}
CORPUS_TOOLS = {"search_corpus"}
SEVERE_WARNING_CODES = {
    "agent_disabled",
    "agent_api_key_missing",
    "agent_base_url_missing",
    "agent_dependency_missing",
    "tool_execution_failed",
    "qdrant_unavailable",
    "no_results",
}

class AgentModelOutput(BaseModel):
    """Strict model-facing output contract for Phase 2."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    tasklist: list[AgentTask] = Field(default_factory=list)


@dataclass(frozen=True)
class ParsedModelOutput:
    answer: str
    tasklist: list[AgentTask]
    warnings: list[AgentWarning]


class SourceGroundingDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    relevant: bool
    reason: str = Field(default="", max_length=300)


class SourceGroundingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[SourceGroundingDecision]


def _resolve_mode(body: AgentChatRequest, settings: Settings) -> AgentMode:
    if body.mode is not None:
        return body.mode
    return AgentMode(settings.agent_default_mode)


def _fallback_tasklist(message: str, source_ids: list[str] | None) -> list[AgentTask]:
    source_scope = ", ".join(source_ids) if source_ids else "relevant project sources"
    topic = message.strip()
    return [
        AgentTask(task=f"Clarify the goal and expected output for: {topic}"),
        AgentTask(task=f"Review {source_scope} for available data and current constraints."),
        AgentTask(task="Break the work into implementation steps and verification checks."),
    ]


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()
    return str(content)


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text


def _extract_json_payload(raw: str) -> str:
    text = _strip_code_fence(raw).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    if text.startswith("{"):
        return text

    start = text.find("{")
    if start < 0:
        return text

    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text[start:], start=start):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1].strip()
    return text


def _warning(code: str, message: str) -> AgentWarning:
    return AgentWarning(code=code, message=message)


def _parse_model_output(raw: str, *, mode: AgentMode, body: AgentChatRequest) -> ParsedModelOutput:
    text = _strip_code_fence(raw).strip()
    warnings: list[AgentWarning] = []
    try:
        data = json.loads(_extract_json_payload(text))
        output = AgentModelOutput.model_validate(data)
        tasklist = output.tasklist
        if mode is AgentMode.TASKLIST and not tasklist:
            warnings.append(
                _warning(
                    "tasklist_missing",
                    "Model returned JSON without tasklist items; generated fallback tasks.",
                )
            )
            tasklist = _fallback_tasklist(body.message, body.source_ids)
        return ParsedModelOutput(output.answer.strip(), tasklist, warnings)
    except Exception:
        if not text:
            raise
        warnings.append(
            _warning(
                "model_response_plain_text",
                "Model returned plain text instead of JSON; used it as the answer.",
            )
        )
        tasklist = _fallback_tasklist(body.message, body.source_ids) if mode is AgentMode.TASKLIST else []
        return ParsedModelOutput(text, tasklist, warnings)


def _is_timeout_exception(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    return "timeout" in name or "timed out" in message or "timeout" in message


def _is_qdrant_exception(exc: Exception) -> bool:
    text = f"{exc.__class__.__name__} {exc}".lower()
    markers = (
        "qdrant",
        "connection refused",
        "connecterror",
        "connectionerror",
        "readtimeout",
        "timed out",
        "timeout",
    )
    return any(marker in text for marker in markers)


def _has_warning(warnings: list[AgentWarning], code: str) -> bool:
    return any(warning.code == code for warning in warnings)


def _add_no_results_warning(
    warnings: list[AgentWarning],
    tool_calls: list[AgentToolCall],
) -> None:
    if not tool_calls or any(call.result_count > 0 for call in tool_calls):
        return
    if _has_warning(warnings, "no_results"):
        return
    searched = ", ".join(call.name for call in tool_calls)
    warnings.append(
        _warning(
            "no_results",
            f"No matching data found from: {searched}.",
        )
    )


def _confidence(
    *,
    tool_calls: list[AgentToolCall],
    sources: list[AgentSource],
    warnings: list[AgentWarning],
) -> AgentConfidence:
    warning_codes = {warning.code for warning in warnings}
    if warning_codes & SEVERE_WARNING_CODES:
        return AgentConfidence.LOW
    if any(call.name in DETERMINISTIC_TOOLS and call.result_count > 0 for call in tool_calls):
        return AgentConfidence.HIGH
    if sources and any(call.name in SEARCH_TOOLS and call.result_count > 0 for call in tool_calls):
        return AgentConfidence.MEDIUM
    return AgentConfidence.LOW


def _source_matches_hard_scope(source: AgentSource, plan: AgentQueryPlan) -> bool:
    if plan.source_ids and source.source_id not in plan.source_ids:
        return False
    if plan.intent == "news_query":
        if source.source_id not in {"philrice_news", "irri"}:
            return False
        if source.page is not None and source.source_id == "irri":
            return False
    if plan.intent == "paper_query" and source.source_id not in {"philrice", "pinoyrice"}:
        return False
    return True


def _source_grounding_prompt(
    *,
    body: AgentChatRequest,
    query_plan: AgentQueryPlan,
    answer: str,
    sources: list[AgentSource],
) -> str:
    source_payload = [
        {
            "index": index,
            "source_id": source.source_id,
            "title": source.title,
            "url": source.url,
            "filename": source.filename,
            "page": source.page,
            "snippet": source.snippet,
        }
        for index, source in enumerate(sources, start=1)
    ]
    payload = {
        "user_question": body.message,
        "query_intent": query_plan.intent,
        "planned_source_ids": query_plan.source_ids,
        "draft_answer": answer,
        "candidate_sources": source_payload,
    }
    return (
        "Verify which candidate sources are relevant citations for the user's question and draft answer.\n"
        "Return only strict JSON with this shape:\n"
        '{"decisions":[{"index":1,"relevant":true,"reason":"short reason"}]}\n'
        "Rules:\n"
        "- Mark relevant=true only if the source directly supports the question or draft answer.\n"
        "- Mark relevant=false for sources that merely share generic agriculture/rice terms.\n"
        "- For broad latest/listing requests, a source may be relevant as a candidate item "
        "if it matches the requested source family, even when the word latest/news/paper is absent.\n"
        "- Do not require exact wording; judge semantic relevance.\n"
        "- Return one decision for every candidate source index.\n\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}"
    )


def _verify_sources_with_ai(
    model: Any,
    *,
    body: AgentChatRequest,
    query_plan: AgentQueryPlan,
    answer: str,
    sources: list[AgentSource],
) -> list[AgentSource] | None:
    if not sources:
        return []
    try:
        response = model.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a strict source-grounding verifier for an agricultural data agent. "
                        "You do not answer the user. You only validate candidate citations."
                    )
                ),
                HumanMessage(
                    content=_source_grounding_prompt(
                        body=body,
                        query_plan=query_plan,
                        answer=answer,
                        sources=sources,
                    )
                ),
            ]
        )
        raw = _content_to_text(getattr(response, "content", response))
        data = json.loads(_strip_code_fence(raw))
        parsed = SourceGroundingOutput.model_validate(data)
    except Exception:
        return None

    source_by_index = {index: source for index, source in enumerate(sources, start=1)}
    keep_indexes = {
        decision.index
        for decision in parsed.decisions
        if decision.relevant and decision.index in source_by_index
    }
    return [source for index, source in source_by_index.items() if index in keep_indexes]


def _is_source_discovery_query(body: AgentChatRequest, query_plan: AgentQueryPlan) -> bool:
    if query_plan.intent not in {"news_query", "paper_query"}:
        return False
    text = body.message.lower()
    discovery_markers = (
        "latest",
        "newest",
        "recent",
        "pinaka",
        "pinakabago",
        "bago",
        "bagong",
        "meron",
        "available",
        "icheck",
        "check",
        "may news",
        "may balita",
        "tayo nito",
        "natin ito",
        "natin nito",
    )
    return any(marker in text for marker in discovery_markers)


def _ground_sources(
    sources: list[AgentSource],
    *,
    body: AgentChatRequest,
    query_plan: AgentQueryPlan,
    answer: str,
    model: Any,
    warnings: list[AgentWarning],
) -> list[AgentSource]:
    if not sources:
        return []
    scoped = [source for source in sources if _source_matches_hard_scope(source, query_plan)]
    verified = _verify_sources_with_ai(
        model,
        body=body,
        query_plan=query_plan,
        answer=answer,
        sources=scoped,
    )
    grounded = scoped if verified is None else verified
    if verified == [] and scoped and _is_source_discovery_query(body, query_plan):
        grounded = scoped
    if len(grounded) < len(sources) and not _has_warning(warnings, "source_relevance_low"):
        warnings.append(
            _warning(
                "source_relevance_low",
                (
                    "Some retrieved sources were removed because the grounding verifier "
                    "or source-scope guard judged them not relevant enough to cite."
                ),
            )
        )
    return grounded


def _maybe_ungrounded_answer(
    answer: str,
    *,
    tool_calls: list[AgentToolCall],
    sources: list[AgentSource],
    warnings: list[AgentWarning],
) -> str:
    if sources:
        return answer
    if any(call.name == "search_corpus" and call.result_count > 0 for call in tool_calls):
        if not _has_warning(warnings, "source_relevance_low"):
            warnings.append(
                _warning(
                    "source_relevance_low",
                    "Retrieved corpus results were not relevant enough to cite as sources.",
                )
            )
        return (
            "May nahanap na corpus records, pero hindi sapat ang match sa tanong para gamitin "
            "bilang source. Subukan magbigay ng mas specific na topic o source."
        )
    return answer


def _tool_cache_key(name: str, args: dict[str, Any]) -> str:
    return json.dumps({"name": name, "args": args}, ensure_ascii=False, sort_keys=True, default=str)


def _tool_family(name: str) -> str | None:
    if name in PRICE_TOOLS:
        return "price"
    if name in YIELD_TOOLS:
        return "yield"
    if name in CORPUS_TOOLS:
        return "corpus"
    return None


def _active_tool_family(
    query_plan: AgentQueryPlan,
    tool_calls: list[AgentToolCall],
) -> str | None:
    preferred_family = _tool_family(query_plan.tool_preference)
    if preferred_family in {"price", "yield"}:
        return preferred_family
    for call in tool_calls:
        family = _tool_family(call.name)
        if family in {"price", "yield"}:
            return family
    return preferred_family


def _tool_allowed_for_family(name: str, active_family: str | None) -> bool:
    if active_family == "price":
        return name in PRICE_TOOLS
    if active_family == "yield":
        return name in YIELD_TOOLS
    return True


def _best_tool_answer(
    tool_calls: list[AgentToolCall],
    tool_results: list[ToolExecutionResult] | None = None,
) -> str | None:
    successful = [call for call in tool_calls if call.result_count > 0]
    if not successful:
        return None

    deterministic = [call for call in successful if call.name in DETERMINISTIC_TOOLS]
    best = deterministic[0] if deterministic else successful[0]
    best_result = next(
        (
            result
            for result in tool_results or []
            if result.name == best.name
            and result.result_count == best.result_count
            and result.arguments == best.arguments
        ),
        None,
    )
    if best.name == "summarize_yield":
        avg_yield = _payload_overall_value(best_result, "avg_yield_ton_ha")
        if avg_yield is not None:
            return (
                f"Average yield: {avg_yield} ton/ha gamit ang filters {best.arguments}. "
                f"Based ito sa {best.result_count} matching row(s)."
            )
        return (
            f"Nakakuha ako ng deterministic yield summary gamit ang filters {best.arguments}. "
            f"May {best.result_count} matching row(s). Tingnan ang `sources` at `tool_calls` para sa detalye."
        )
    if best.name == "summarize_prices":
        avg_price = _payload_overall_value(best_result, "avg_price_php_per_kg")
        if avg_price is not None:
            return (
                f"Average price: PHP {avg_price}/kg gamit ang filters {best.arguments}. "
                f"Based ito sa {best.result_count} matching row(s)."
            )
        return (
            f"Nakakuha ako ng deterministic price summary gamit ang filters {best.arguments}. "
            f"May {best.result_count} matching row(s). Tingnan ang `sources` at `tool_calls` para sa detalye."
        )
    return (
        f"Nakahanap ako ng {best.result_count} matching result(s) gamit ang `{best.name}`. "
        "Tingnan ang `sources` at `tool_calls` para sa detalye."
    )


def _payload_overall_value(tool_result: ToolExecutionResult | None, key: str) -> object | None:
    if tool_result is None:
        return None
    payload = tool_result.payload
    if not isinstance(payload, dict):
        return None
    overall = payload.get("overall")
    if not isinstance(overall, dict):
        return None
    return overall.get(key)


def _tool_backed_fallback_response(
    *,
    body: AgentChatRequest,
    mode: AgentMode,
    warnings: list[AgentWarning],
    started: float,
    tool_calls: list[AgentToolCall],
    tool_results: list[ToolExecutionResult],
    sources: list[AgentSource],
) -> AgentChatResponse | None:
    answer = _best_tool_answer(tool_calls, tool_results)
    if not answer:
        return None
    deduped_sources = _dedupe_sources(sources)
    return AgentChatResponse(
        answer=answer,
        tasklist=_fallback_tasklist(body.message, body.source_ids) if mode == AgentMode.TASKLIST else [],
        tool_calls=tool_calls,
        sources=deduped_sources,
        warnings=warnings,
        confidence=_confidence(tool_calls=tool_calls, sources=deduped_sources, warnings=warnings),
        took_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def _fallback_response(
    *,
    body: AgentChatRequest,
    mode: AgentMode,
    warnings: list[AgentWarning],
    started: float,
    tool_calls: list[AgentToolCall] | None = None,
    sources: list[AgentSource] | None = None,
) -> AgentChatResponse:
    if mode == AgentMode.TASKLIST:
        answer = (
            "Narito muna ang fallback tasklist. Hindi pa nakatawag sa LangChain model dahil may "
            "configuration o provider issue."
        )
        tasklist = _fallback_tasklist(body.message, body.source_ids)
    else:
        answer = (
            "Agent route is available, but the LangChain model call is not configured yet. "
            "Set AGENT_PROVIDER, AGENT_API_KEY, and AGENT_MODEL to enable live answers."
        )
        tasklist = []
    return AgentChatResponse(
        answer=answer,
        tasklist=tasklist,
        tool_calls=tool_calls or [],
        sources=sources or [],
        warnings=warnings,
        confidence=AgentConfidence.LOW,
        took_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def _bind_tools_if_supported(model: Any, tools: list[BaseTool]) -> Any:
    if not tools:
        return model
    bind_tools = getattr(model, "bind_tools", None)
    if callable(bind_tools):
        return bind_tools(tools)
    return model


def _tool_call_parts(raw_call: object) -> tuple[str, dict[str, Any], str] | None:
    if not isinstance(raw_call, dict):
        return None

    call_id = str(raw_call.get("id") or raw_call.get("name") or "tool_call")
    name = raw_call.get("name")
    args = raw_call.get("args")

    function = raw_call.get("function")
    if isinstance(function, dict):
        name = name or function.get("name")
        args = args or function.get("arguments")

    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}

    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(args, dict):
        args = {}
    return name.strip(), dict(args), call_id


def _extract_tool_calls(message: object) -> list[tuple[str, dict[str, Any], str]]:
    raw_calls = getattr(message, "tool_calls", None)
    if not raw_calls:
        additional = getattr(message, "additional_kwargs", {})
        if isinstance(additional, dict):
            raw_calls = additional.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []

    out: list[tuple[str, dict[str, Any], str]] = []
    for raw_call in raw_calls:
        parsed = _tool_call_parts(raw_call)
        if parsed is not None:
            out.append(parsed)
    return out


def _latest_requested(message: str) -> bool:
    text = message.lower()
    markers = (
        "latest",
        "newest",
        "recent",
        "pinakabago",
        "pinaka bago",
        "bagong balita",
        "latest news",
    )
    return any(marker in text for marker in markers)


def _normalize_tool_args(
    name: str,
    args: dict[str, Any],
    body: AgentChatRequest,
    query_plan: AgentQueryPlan,
) -> dict[str, Any]:
    normalized = dict(args)
    if name == "search_corpus":
        if query_plan.source_ids:
            normalized["source_ids"] = query_plan.source_ids
        if _latest_requested(body.message) and not normalized.get("sort_by"):
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
            normalized["query"] = body.message
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
            normalized["query"] = body.message
    return normalized


def _farmer_context_text(result: FarmerIntentResult) -> str:
    parts = [
        f"user_type={result.user_type}",
        f"intent={result.intent}",
        f"language={result.language}",
        f"location={result.location or 'not specified'}",
        f"crop={result.crop or 'not specified'}",
        f"missing_context={result.missing_context}",
    ]
    if result.clarification_question:
        parts.append(f"clarification_question={result.clarification_question}")
    if result.recommended_source_ids:
        parts.append(f"recommended_source_ids={', '.join(result.recommended_source_ids)}")
    return "\n".join(parts)


def _tool_message(call_id: str, result: ToolExecutionResult) -> ToolMessage:
    content = json.dumps(
        {
            "summary": result.summary,
            "result_count": result.result_count,
            "payload": result.payload,
        },
        ensure_ascii=False,
        default=str,
    )
    return ToolMessage(content=content, tool_call_id=call_id, name=result.name)


def _dedupe_sources(sources: list[AgentSource]) -> list[AgentSource]:
    seen: set[tuple[object, ...]] = set()
    out: list[AgentSource] = []
    for source in sources:
        key = (source.source_id, source.url, source.filename, source.page, source.snippet)
        if key in seen:
            continue
        seen.add(key)
        out.append(source)
    return out


def _effective_user_type(
    body: AgentChatRequest,
    *,
    api_scope: object | None = None,
    current_user: object | None = None,
) -> str:
    requested = body.user_type.value
    if requested not in {"admin", "developer"}:
        return requested

    from src.api.auth import AuthScope

    if api_scope is AuthScope.ADMIN:
        return requested
    role = getattr(current_user, "role", None) if current_user is not None else None
    if isinstance(role, str) and role.lower() in {"admin", "developer"}:
        return requested
    return "farmer"


def run_agent_chat(
    body: AgentChatRequest,
    settings: Settings,
    *,
    store: QdrantStoreProtocol | None = None,
    api_scope: object | None = None,
    current_user: object | None = None,
) -> AgentChatResponse:
    started = time.perf_counter()
    mode = _resolve_mode(body, settings)
    warnings: list[AgentWarning] = []
    tool_call_records: list[AgentToolCall] = []
    tool_results: list[ToolExecutionResult] = []
    sources: list[AgentSource] = []
    tool_result_cache: dict[str, ToolExecutionResult] = {}

    if not settings.agent_enabled:
        warnings.append(_warning("agent_disabled", "Agent is disabled by configuration."))
        return _fallback_response(body=body, mode=mode, warnings=warnings, started=started)

    try:
        model = create_chat_model(settings)
    except AgentClientError as exc:
        warnings.append(_warning(exc.code, exc.message))
        return _fallback_response(body=body, mode=mode, warnings=warnings, started=started)

    farmer_context = infer_farmer_intent(
        message=body.message,
        user_type=_effective_user_type(body, api_scope=api_scope, current_user=current_user),
        location=body.location,
        crop=body.crop,
        language=body.language,
        source_ids=body.source_ids,
    )
    query_plan = build_query_plan(
        message=body.message,
        farmer_context=farmer_context,
        source_ids=body.source_ids,
    )
    warnings.extend(query_plan.warnings)

    messages: list[BaseMessage] = build_agent_messages(
        message=body.message,
        mode=mode,
        history=body.history,
        source_ids=body.source_ids,
        farmer_context=_farmer_context_text(farmer_context),
        query_plan_context=query_plan_text(query_plan),
    )
    tools = (
        build_agent_tools(
            ToolExecutionContext(
                store,
                summarize_max_rows=settings.agent_summarize_max_rows,
            )
        )
        if store is not None
        else []
    )
    tool_by_name = {tool.name: tool for tool in tools}
    model_for_call = _bind_tools_if_supported(model, tools)
    remaining_tool_calls = (
        body.max_tool_calls if body.max_tool_calls is not None else settings.agent_max_tool_calls
    )

    while True:
        try:
            result = model_for_call.invoke(messages)
        except Exception as exc:
            code = "model_timeout" if _is_timeout_exception(exc) else "model_provider_error"
            message = (
                "LangChain model call timed out."
                if code == "model_timeout"
                else f"LangChain model call failed ({exc.__class__.__name__})."
            )
            warnings.append(_warning(code, message))
            _add_no_results_warning(warnings, tool_call_records)
            tool_backed = _tool_backed_fallback_response(
                body=body,
                mode=mode,
                warnings=warnings,
                started=started,
                tool_calls=tool_call_records,
                tool_results=tool_results,
                sources=_dedupe_sources(sources),
            )
            if tool_backed is not None:
                return tool_backed
            return _fallback_response(
                body=body,
                mode=mode,
                warnings=warnings,
                started=started,
                tool_calls=tool_call_records,
                sources=_dedupe_sources(sources),
            )

        tool_calls = _extract_tool_calls(result)
        if tool_calls:
            if remaining_tool_calls <= 0:
                warnings.append(
                    _warning(
                        "tool_limit_reached",
                        "Model requested more tool calls than AGENT_MAX_TOOL_CALLS allows.",
                    )
                )
                tool_backed = _tool_backed_fallback_response(
                    body=body,
                    mode=mode,
                    warnings=warnings,
                    started=started,
                    tool_calls=tool_call_records,
                    tool_results=tool_results,
                    sources=_dedupe_sources(sources),
                )
                if tool_backed is not None:
                    return tool_backed
                return _fallback_response(
                    body=body,
                    mode=mode,
                    warnings=warnings,
                    started=started,
                    tool_calls=tool_call_records,
                    sources=_dedupe_sources(sources),
                )

            if isinstance(result, BaseMessage):
                messages.append(result)

            for name, args, call_id in tool_calls:
                args = _normalize_tool_args(name, args, body, query_plan)
                active_family = _active_tool_family(query_plan, tool_call_records)
                if not _tool_allowed_for_family(name, active_family):
                    warnings.append(
                        _warning(
                            "tool_scope_blocked",
                            (
                                f"Blocked `{name}` because this request is scoped to "
                                f"{active_family} data."
                            ),
                        )
                    )
                    messages.append(
                        ToolMessage(
                            content=json.dumps(
                                {
                                    "error": (
                                        f"{name} is not relevant for a "
                                        f"{active_family} data request."
                                    )
                                }
                            ),
                            tool_call_id=call_id,
                            name=name,
                        )
                    )
                    remaining_tool_calls -= 1
                    continue
                cache_key = _tool_cache_key(name, args)
                cached_result = tool_result_cache.get(cache_key)
                if cached_result is not None:
                    messages.append(_tool_message(call_id, cached_result))
                    continue
                if remaining_tool_calls <= 0:
                    warnings.append(
                        _warning(
                            "tool_limit_reached",
                            "Model requested more tool calls than AGENT_MAX_TOOL_CALLS allows.",
                        )
                    )
                    tool_backed = _tool_backed_fallback_response(
                        body=body,
                        mode=mode,
                        warnings=warnings,
                        started=started,
                        tool_calls=tool_call_records,
                        tool_results=tool_results,
                        sources=_dedupe_sources(sources),
                    )
                    if tool_backed is not None:
                        return tool_backed
                    return _fallback_response(
                        body=body,
                        mode=mode,
                        warnings=warnings,
                        started=started,
                        tool_calls=tool_call_records,
                        sources=_dedupe_sources(sources),
                    )
                tool = tool_by_name.get(name)
                if tool is None:
                    warnings.append(_warning("unknown_tool", f"Model requested unknown tool: {name}"))
                    messages.append(
                        ToolMessage(
                            content=json.dumps({"error": f"Unknown tool: {name}"}),
                            tool_call_id=call_id,
                            name=name,
                        )
                    )
                    remaining_tool_calls -= 1
                    continue

                try:
                    tool_result = tool.invoke(args)
                    if not isinstance(tool_result, ToolExecutionResult):
                        raise TypeError("Tool returned an unexpected result type.")
                except Exception as exc:
                    code = "qdrant_unavailable" if _is_qdrant_exception(exc) else "tool_execution_failed"
                    message = (
                        f"Tool {name} could not reach Qdrant or storage ({exc.__class__.__name__})."
                        if code == "qdrant_unavailable"
                        else f"Tool {name} failed ({exc.__class__.__name__})."
                    )
                    warnings.append(
                        _warning(code, message)
                    )
                    messages.append(
                        ToolMessage(
                            content=json.dumps({"error": f"{name} failed"}),
                            tool_call_id=call_id,
                            name=name,
                        )
                    )
                    remaining_tool_calls -= 1
                    continue

                tool_call_records.append(
                    AgentToolCall(
                        name=tool_result.name,
                        arguments=tool_result.arguments,
                        summary=tool_result.summary,
                        result_count=tool_result.result_count,
                    )
                )
                sources.extend(tool_result.sources)
                tool_results.append(tool_result)
                tool_result_cache[cache_key] = tool_result
                messages.append(_tool_message(call_id, tool_result))
                remaining_tool_calls -= 1
            continue

        _add_no_results_warning(warnings, tool_call_records)
        try:
            raw_content = getattr(result, "content", result)
            parsed = _parse_model_output(_content_to_text(raw_content), mode=mode, body=body)
            warnings.extend(parsed.warnings)
        except Exception as exc:
            warnings.append(
                _warning(
                    "model_provider_error",
                    f"LangChain model call failed ({exc.__class__.__name__}).",
                )
            )
            return _fallback_response(
                body=body,
                mode=mode,
                warnings=warnings,
                started=started,
                tool_calls=tool_call_records,
                sources=_dedupe_sources(sources),
            )
        break

    if not parsed.answer:
        warnings.append(_warning("empty_model_answer", "The LangChain model returned an empty answer."))
        return _fallback_response(
            body=body,
            mode=mode,
            warnings=warnings,
            started=started,
            tool_calls=tool_call_records,
            sources=_dedupe_sources(sources),
        )

    grounded_sources = _dedupe_sources(
        _ground_sources(
            sources,
            body=body,
            query_plan=query_plan,
            answer=parsed.answer,
            model=model,
            warnings=warnings,
        )
    )
    answer = _maybe_ungrounded_answer(
        parsed.answer,
        tool_calls=tool_call_records,
        sources=grounded_sources,
        warnings=warnings,
    )

    return AgentChatResponse(
        answer=answer,
        tasklist=parsed.tasklist if mode == AgentMode.TASKLIST else [],
        tool_calls=tool_call_records,
        sources=grounded_sources,
        warnings=warnings,
        confidence=_confidence(
            tool_calls=tool_call_records,
            sources=grounded_sources,
            warnings=warnings,
        ),
        took_ms=round((time.perf_counter() - started) * 1000, 2),
    )
