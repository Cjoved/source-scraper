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


AGENT_CHAT_DESCRIPTION = """
LangChain-backed chat/tasklist agent over read-only scraper data.

Use `mode="tasklist"` for planning/checklists. Use `mode="chat"` for data questions and farmer-facing answers.
For PRiSM yield and OpenSTAT price questions, omit `source_ids`; those filters apply only to corpus/news tools.
For narrative/news/advisory questions, pass corpus source ids such as `philrice_news`, `irri`, `philrice`, or `pinoyrice`.
"""

AGENT_CHAT_EXAMPLES = {
    "tasklist": {
        "summary": "Tasklist planning",
        "value": {
            "message": "Gawan mo ako ng tasklist para linisin ang PhilRice News corpus",
            "mode": "tasklist",
            "source_ids": ["philrice_news"],
        },
    },
    "yield_summary": {
        "summary": "PRiSM yield summary",
        "value": {
            "message": "Ano ang average yield ng palay sa Laguna 2 years ago?",
            "mode": "chat",
        },
    },
    "price_summary": {
        "summary": "OpenSTAT price summary",
        "value": {
            "message": "Ano ang average farmgate price ng palay sa Nueva Ecija 3 years ago?",
            "mode": "chat",
        },
    },
    "latest_news": {
        "summary": "Latest corpus/news search",
        "value": {
            "message": "Ano ang latest news sa IRRI tungkol sa rice farming?",
            "mode": "chat",
            "source_ids": ["irri"],
        },
    },
}

AGENT_CHAT_RESPONSE_EXAMPLE = {
    "answer": "Average yield: 4.5 ton/ha gamit ang filters {'province': 'Laguna', 'year_min': 2024, 'year_max': 2024}.",
    "tasklist": [],
    "tool_calls": [
        {
            "name": "summarize_yield",
            "arguments": {"province": "Laguna", "year_min": 2024, "year_max": 2024},
            "summary": "Computed yield summary over 1 row(s).",
            "result_count": 1,
        }
    ],
    "sources": [
        {
            "source_id": "prism_yield_records",
            "title": None,
            "url": None,
            "filename": None,
            "page": None,
            "snippet": "Deterministic yield summary over 1 row(s). Filters: {'province': 'Laguna', 'year_min': 2024, 'year_max': 2024}.",
        }
    ],
    "warnings": [],
    "confidence": "high",
    "took_ms": 42.0,
}


@router.post(
    "/agent/chat",
    response_model=AgentChatResponse,
    summary="Chat/tasklist agent over scraper data",
    description=AGENT_CHAT_DESCRIPTION,
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": AGENT_CHAT_EXAMPLES,
                }
            }
        },
        "responses": {
            "200": {
                "description": "Agent answer with optional tasklist, tool trace, sources, warnings, and confidence.",
                "content": {
                    "application/json": {
                        "example": AGENT_CHAT_RESPONSE_EXAMPLE,
                    }
                },
            }
        },
    },
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
