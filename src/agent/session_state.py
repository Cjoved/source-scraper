"""Resolve and update client-carried agent session state."""

from __future__ import annotations

from src.agent.intent import _infer_crop, infer_reply_language
from src.agent.query_planner import infer_crop_from_user_history, infer_location, infer_location_from_user_history
from src.api.schemas import AgentChatRequest, AgentSessionState, AgentSource, AgentToolCall
from src.agent.query_planner import AgentQueryPlan

_PRICE_TOOLS = frozenset({"summarize_prices", "search_prices"})
_YIELD_TOOLS = frozenset({"summarize_yield", "search_yield_knowledge"})
_DATA_TOOLS = _PRICE_TOOLS | _YIELD_TOOLS


def resolve_session_state(body: AgentChatRequest) -> AgentSessionState:
    """Merge prior session, explicit request fields, current message, and user history."""
    base = body.session_state.model_copy(deep=True) if body.session_state else AgentSessionState()

    location = (
        infer_location(body.message, body.location)
        or base.location
        or infer_location_from_user_history(body.history)
    )
    crop = _infer_crop(body.message, body.crop) or base.crop or infer_crop_from_user_history(body.history)
    language = infer_reply_language(body.message, body.language, base.language)

    return AgentSessionState(
        location=location,
        crop=crop,
        language=language,
        last_intent=base.last_intent,
        last_tool_name=base.last_tool_name,
        last_tool_args=base.last_tool_args,
        last_source_ids=base.last_source_ids,
    )


def update_session_state(
    state: AgentSessionState,
    *,
    query_plan: AgentQueryPlan,
    tool_calls: list[AgentToolCall],
    sources: list[AgentSource],
    source_ids: list[str] | None = None,
) -> AgentSessionState:
    """Persist verified facts from tool execution only."""
    location = state.location
    crop = state.crop
    last_tool_name: str | None = state.last_tool_name
    last_tool_args: dict[str, object] | None = state.last_tool_args
    last_source_ids = list(state.last_source_ids) if state.last_source_ids else None

    successful = [call for call in tool_calls if call.result_count > 0 or call.name == "list_openstat_commodities"]
    if successful:
        last_call = successful[-1]
        last_tool_name = last_call.name
        last_tool_args = dict(last_call.arguments)

    for call in reversed(successful):
        args = call.arguments
        if call.name in _PRICE_TOOLS and args.get("geolocation"):
            location = str(args["geolocation"])
            break
        if call.name in _YIELD_TOOLS and args.get("province"):
            location = str(args["province"])
            break

    for call in reversed(successful):
        args = call.arguments
        commodity = args.get("commodity")
        if isinstance(commodity, str) and commodity.strip():
            lowered = commodity.lower()
            if lowered in {"palay", "rice", "bigas"}:
                crop = "palay"
            elif lowered in {"corn", "mais"}:
                crop = "corn"
            break

    if source_ids:
        last_source_ids = list(source_ids)
    elif query_plan.source_ids:
        last_source_ids = list(query_plan.source_ids)

    return AgentSessionState(
        location=location,
        crop=crop,
        language=state.language,
        last_intent=query_plan.intent,
        last_tool_name=last_tool_name,
        last_tool_args=last_tool_args,
        last_source_ids=last_source_ids,
    )


def session_state_context_text(state: AgentSessionState) -> str:
    parts = [
        f"location={state.location or 'not specified'}",
        f"crop={state.crop or 'not specified'}",
        f"last_intent={state.last_intent or 'not specified'}",
        f"last_tool={state.last_tool_name or 'not specified'}",
    ]
    if state.last_source_ids:
        parts.append(f"last_source_ids={', '.join(state.last_source_ids)}")
    return "\n".join(parts)
