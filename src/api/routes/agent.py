"""AI chat/tasklist agent route."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.agent.orchestrator import run_agent_chat
from src.api.auth import require_public
from src.api.deps import get_qdrant_store
from src.api.rate_limit import limiter
from src.api.schemas import AgentChatRequest, AgentChatResponse
from src.api.settings import Settings, get_settings
from src.storage.qdrant_store import QdrantStoreProtocol

router = APIRouter(tags=["agent"])


@router.post(
    "/agent/chat",
    response_model=AgentChatResponse,
    summary="Chat/tasklist agent over scraper data",
    description=(
        "LangChain-backed chat/tasklist agent. Uses read-only tools over indexed yield, "
        "price, and corpus data when the model requests project data."
    ),
)
@limiter.limit("10/minute")
def agent_chat(
    request: Request,
    body: AgentChatRequest,
    _scope: object = Depends(require_public),
    settings: Settings = Depends(get_settings),
    store: QdrantStoreProtocol = Depends(get_qdrant_store),
) -> AgentChatResponse:
    del request
    return run_agent_chat(body, settings, store=store)
