"""Pure helpers for the optional Chainlit agent demo UI.

This module deliberately has no Chainlit imports so it can be unit-tested without
installing UI dependencies or calling the live API.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_UI_MODE = "chat"
MAX_UI_HISTORY = 10
VALID_UI_MODES = {"chat", "tasklist"}


@dataclass(frozen=True)
class UiCommandResult:
    """Result of applying a demo UI slash command."""

    should_call_api: bool
    message: str
    mode: str
    source_ids: list[str] | None
    notice: str | None = None


def parse_source_ids(raw: str | None) -> list[str] | None:
    """Parse comma/space separated source ids for the agent API."""

    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned or cleaned.lower() in {"none", "clear", "all", "-"}:
        return None

    seen: set[str] = set()
    out: list[str] = []
    for part in cleaned.replace(",", " ").split():
        source_id = part.strip().lower()
        if not source_id or source_id in seen:
            continue
        seen.add(source_id)
        out.append(source_id)
    return out or None


def trim_history(history: list[dict[str, Any]], *, limit: int = MAX_UI_HISTORY) -> list[dict[str, str]]:
    """Keep only valid user/assistant messages that fit the API contract."""

    valid: list[dict[str, str]] = []
    for item in history:
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            continue
        content = content.strip()
        if not content:
            continue
        valid.append({"role": role, "content": content[:4000]})
    return valid[-limit:]


def build_agent_payload(
    *,
    message: str,
    mode: str = DEFAULT_UI_MODE,
    source_ids: list[str] | None = None,
    history: list[dict[str, Any]] | None = None,
    location: str | None = None,
    crop: str | None = None,
    language: str | None = None,
    max_tool_calls: int | None = None,
) -> dict[str, Any]:
    """Build the `/v1/agent/chat` request payload from UI state."""

    normalized_mode = mode if mode in VALID_UI_MODES else DEFAULT_UI_MODE
    payload: dict[str, Any] = {
        "message": message.strip(),
        "mode": normalized_mode,
    }
    trimmed_history = trim_history(history or [])
    if trimmed_history:
        payload["history"] = trimmed_history
    if source_ids:
        payload["source_ids"] = source_ids[:10]
    if location:
        payload["location"] = location.strip()
    if crop:
        payload["crop"] = crop.strip()
    if language:
        payload["language"] = language.strip()
    if max_tool_calls is not None:
        payload["max_tool_calls"] = max_tool_calls
    return payload


def apply_ui_command(
    text: str,
    *,
    current_mode: str = DEFAULT_UI_MODE,
    current_source_ids: list[str] | None = None,
) -> UiCommandResult:
    """Apply supported slash commands and return the next UI state."""

    message = text.strip()
    mode = current_mode if current_mode in VALID_UI_MODES else DEFAULT_UI_MODE
    source_ids = current_source_ids
    if not message.startswith("/"):
        return UiCommandResult(True, message, mode, source_ids)

    command, _, rest = message.partition(" ")
    command = command.lower()
    rest = rest.strip()

    if command == "/sources":
        source_scope, query = _split_command_rest(rest)
        source_ids = parse_source_ids(source_scope)
        label = ", ".join(source_ids) if source_ids else "all corpus sources"
        if query:
            return UiCommandResult(True, query, mode, source_ids)
        return UiCommandResult(False, "", mode, source_ids, f"Source scope set to: {label}.")

    if command == "/mode":
        requested = rest.lower()
        if requested not in VALID_UI_MODES:
            return UiCommandResult(
                False,
                "",
                mode,
                source_ids,
                "Invalid mode. Use `/mode chat` or `/mode tasklist`.",
            )
        return UiCommandResult(False, "", requested, source_ids, f"Mode set to: {requested}.")

    if command in {"/tasklist", "/chat"}:
        mode = command.removeprefix("/")
        if not rest:
            return UiCommandResult(False, "", mode, source_ids, f"Mode set to: {mode}.")
        return UiCommandResult(True, rest, mode, source_ids)

    return UiCommandResult(
        False,
        "",
        mode,
        source_ids,
        "Unknown command. Try `/tasklist`, `/chat`, `/mode chat`, or `/sources irri,philrice_news`.",
    )


def _split_command_rest(rest: str) -> tuple[str, str]:
    first, separator, remainder = rest.partition("\n")
    if not separator:
        return first.strip(), ""
    return first.strip(), remainder.strip()


def format_agent_response(response: dict[str, Any]) -> str:
    """Format an agent API response into Chainlit-friendly Markdown."""

    parts: list[str] = []
    confidence = response.get("confidence")
    took_ms = response.get("took_ms")
    status_bits = []
    if confidence:
        status_bits.append(f"confidence: `{confidence}`")
    if isinstance(took_ms, int | float):
        status_bits.append(f"took: `{took_ms:.2f} ms`")
    if status_bits:
        parts.append("**Agent response** · " + " · ".join(status_bits))

    parts.append(str(response.get("answer") or "No answer returned.").strip())

    tasklist = response.get("tasklist")
    if isinstance(tasklist, list) and tasklist:
        lines = ["### Tasklist"]
        for idx, task in enumerate(tasklist, start=1):
            if not isinstance(task, dict):
                continue
            status = task.get("status", "pending")
            text = task.get("task", "")
            lines.append(f"{idx}. **{text}**")
            lines.append(f"   - status: `{status}`")
        parts.append("\n".join(lines))

    sources = response.get("sources")
    if isinstance(sources, list) and sources:
        parts.append(_format_sources(sources))

    tool_calls = response.get("tool_calls")
    if isinstance(tool_calls, list) and tool_calls:
        parts.append(_format_tool_calls(tool_calls))

    warnings = response.get("warnings")
    if isinstance(warnings, list) and warnings:
        parts.append(_format_warnings(warnings))

    return "\n\n".join(part for part in parts if part)


def _format_sources(sources: list[Any]) -> str:
    lines = ["### Sources", ""]
    for idx, source in enumerate(sources, start=1):
        if not isinstance(source, dict):
            continue
        title = source.get("title") or source.get("filename") or source.get("source_id") or "Untitled"
        url = source.get("url")
        source_id = source.get("source_id")
        snippet = source.get("snippet")
        page = source.get("page")
        safe_url = url if isinstance(url, str) and url.startswith("https://") else None
        label = f"[{title}]({safe_url})" if safe_url else str(title)
        meta = []
        if source_id:
            meta.append(f"`{source_id}`")
        if page is not None:
            meta.append(f"page `{page}`")
        suffix = f" ({', '.join(meta)})" if meta else ""
        lines.append(f"**{idx}. {label}**{suffix}")
        if snippet:
            lines.append(f"   > {str(snippet).strip()}")
    return "\n".join(lines)


def _format_tool_calls(tool_calls: list[Any]) -> str:
    lines = ["### Tool Trace", ""]
    for idx, call in enumerate(tool_calls, start=1):
        if not isinstance(call, dict):
            continue
        name = call.get("name", "unknown_tool")
        result_count = call.get("result_count", 0)
        summary = call.get("summary", "")
        args = call.get("arguments") or {}
        lines.append(f"**{idx}. `{name}`**")
        lines.append(f"   - results: `{result_count}`")
        if summary:
            lines.append(f"   - summary: {summary}")
        if args:
            lines.append(f"   - args: `{args}`")
    return "\n".join(lines)


def _format_warnings(warnings: list[Any]) -> str:
    lines = ["### Warnings", ""]
    for warning in warnings:
        if not isinstance(warning, dict):
            continue
        code = warning.get("code", "warning")
        message = warning.get("message", "")
        lines.append(f"- `{code}`: {message}")
    return "\n".join(lines)
