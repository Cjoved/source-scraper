"""AI chat/tasklist agent route.

Phase 1 exposes the stable API contract and returns a deterministic tasklist
placeholder. Model calls and read-only tool execution are added in later phases.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from src.api.auth import require_public
from src.api.rate_limit import limiter
from src.api.schemas import AgentChatRequest, AgentChatResponse, AgentMode, AgentTask, AgentWarning
from src.api.settings import Settings, get_settings

router = APIRouter(tags=["agent"])


def _resolve_mode(body: AgentChatRequest, settings: Settings) -> AgentMode:
    if body.mode is not None:
        return body.mode
    return AgentMode(settings.agent_default_mode)


def _placeholder_tasklist(message: str, source_ids: list[str] | None) -> list[AgentTask]:
    source_scope = ", ".join(source_ids) if source_ids else "relevant project sources"
    topic = message.strip()
    return [
        AgentTask(task=f"Clarify the goal and expected output for: {topic}"),
        AgentTask(task=f"Check {source_scope} for existing data, constraints, and useful context."),
        AgentTask(task="Break the work into implementation steps, verification steps, and follow-up notes."),
    ]


@router.post(
    "/agent/chat",
    response_model=AgentChatResponse,
    summary="Chat/tasklist agent over scraper data",
    description=(
        "Phase 1 endpoint for the AI agent contract. It is read-only and returns "
        "a deterministic chat or tasklist response without calling an LLM or Qdrant yet."
    ),
)
@limiter.limit("10/minute")
def agent_chat(
    request: Request,
    body: AgentChatRequest,
    _scope: object = Depends(require_public),
    settings: Settings = Depends(get_settings),
) -> AgentChatResponse:
    del request
    started = time.perf_counter()
    mode = _resolve_mode(body, settings)
    warnings: list[AgentWarning] = []
    if not settings.agent_enabled:
        warnings.append(
            AgentWarning(
                code="agent_disabled",
                message="Agent is disabled by configuration.",
            )
        )

    if mode is AgentMode.TASKLIST:
        answer = "Narito ang Phase 1 tasklist draft. LLM/tool calling will be added in later phases."
        tasklist = _placeholder_tasklist(body.message, body.source_ids)
    else:
        answer = (
            "Agent API contract is ready. Phase 1 does not call Kimi, DeepSeek, "
            "or project data tools yet."
        )
        tasklist = []

    took_ms = round((time.perf_counter() - started) * 1000, 2)
    return AgentChatResponse(
        answer=answer,
        tasklist=tasklist,
        tool_calls=[],
        sources=[],
        warnings=warnings,
        took_ms=took_ms,
    )
