"""Phase 2 LangChain agent orchestration."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from src.agent.client import AgentClientError, create_chat_model
from src.agent.prompts import build_agent_messages
from src.agent.tools import ToolExecutionContext, ToolExecutionResult, build_agent_tools
from src.api.schemas import (
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


def _warning(code: str, message: str) -> AgentWarning:
    return AgentWarning(code=code, message=message)


def _parse_model_output(raw: str, *, mode: AgentMode, body: AgentChatRequest) -> ParsedModelOutput:
    text = _strip_code_fence(raw).strip()
    warnings: list[AgentWarning] = []
    try:
        data = json.loads(text)
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


def run_agent_chat(
    body: AgentChatRequest,
    settings: Settings,
    *,
    store: QdrantStoreProtocol | None = None,
) -> AgentChatResponse:
    started = time.perf_counter()
    mode = _resolve_mode(body, settings)
    warnings: list[AgentWarning] = []
    tool_call_records: list[AgentToolCall] = []
    sources: list[AgentSource] = []

    if not settings.agent_enabled:
        warnings.append(_warning("agent_disabled", "Agent is disabled by configuration."))
        return _fallback_response(body=body, mode=mode, warnings=warnings, started=started)

    try:
        model = create_chat_model(settings)
    except AgentClientError as exc:
        warnings.append(_warning(exc.code, exc.message))
        return _fallback_response(body=body, mode=mode, warnings=warnings, started=started)

    messages: list[BaseMessage] = build_agent_messages(
        message=body.message,
        mode=mode,
        history=body.history,
        source_ids=body.source_ids,
    )
    tools = build_agent_tools(ToolExecutionContext(store)) if store is not None else []
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
                if remaining_tool_calls <= 0:
                    warnings.append(
                        _warning(
                            "tool_limit_reached",
                            "Model requested more tool calls than AGENT_MAX_TOOL_CALLS allows.",
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
                    warnings.append(
                        _warning("tool_execution_failed", f"Tool {name} failed ({exc.__class__.__name__}).")
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
                messages.append(_tool_message(call_id, tool_result))
                remaining_tool_calls -= 1
            continue

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

    return AgentChatResponse(
        answer=parsed.answer,
        tasklist=parsed.tasklist if mode == AgentMode.TASKLIST else [],
        tool_calls=tool_call_records,
        sources=_dedupe_sources(sources),
        warnings=warnings,
        took_ms=round((time.perf_counter() - started) * 1000, 2),
    )
