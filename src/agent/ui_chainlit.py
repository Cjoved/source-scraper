"""Optional Chainlit demo UI for the AgriDataAgent.

Run with:
    uv run chainlit run src/agent/ui_chainlit.py -w --port 8001
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import chainlit as cl  # pyright: ignore[reportMissingImports] - optional `ui` extra.
import httpx
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Chainlit does not load project .env by itself; pick up AGENT_UI_* for local runs.
load_dotenv(_REPO_ROOT / ".env")

from src.agent.ui_helpers import (
    DEFAULT_UI_MODE,
    apply_ui_command,
    build_agent_payload,
    format_agent_response,
)

DEFAULT_AGENT_API_URL = "http://127.0.0.1:8000/v1/agent/chat"
DEFAULT_TIMEOUT_SECONDS = 90.0
STREAM_CHUNK_SIZE = 36
PROFILE_FARMER = "Farmer Chat"
PROFILE_DATA = "Data Explorer"
PROFILE_TASKLIST = "Tasklist Planner"


def _api_url() -> str:
    return os.getenv("AGENT_UI_API_URL", DEFAULT_AGENT_API_URL).strip() or DEFAULT_AGENT_API_URL


def _api_key() -> str | None:
    value = os.getenv("AGENT_UI_API_KEY", "").strip()
    return value or None


def _timeout_seconds() -> float:
    raw = os.getenv("AGENT_UI_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return max(float(raw), 1.0)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "accept": "application/json"}
    api_key = _api_key()
    if api_key:
        headers["X-API-Key"] = api_key
    return headers


def _history() -> list[dict[str, str]]:
    history = cl.user_session.get("history")
    return history if isinstance(history, list) else []


def _set_history(history: list[dict[str, str]]) -> None:
    cl.user_session.set("history", history)


def _mode() -> str:
    mode = cl.user_session.get("mode")
    return mode if isinstance(mode, str) else DEFAULT_UI_MODE


def _set_mode(mode: str) -> None:
    cl.user_session.set("mode", mode)


def _source_ids() -> list[str] | None:
    source_ids = cl.user_session.get("source_ids")
    return source_ids if isinstance(source_ids, list) else None


def _set_source_ids(source_ids: list[str] | None) -> None:
    cl.user_session.set("source_ids", source_ids)


def _profile_defaults(profile: str | None) -> tuple[str, list[str] | None]:
    if profile == PROFILE_TASKLIST:
        return "tasklist", None
    return DEFAULT_UI_MODE, None


async def _call_agent_api(payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=_timeout_seconds()) as client:
        response = await client.post(_api_url(), json=payload, headers=_headers())
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise TypeError("Agent API returned a non-object response.")
        return data


async def _stream_markdown(markdown: str) -> None:
    msg = await cl.Message(content="", author="AgriDataAgent").send()
    for start in range(0, len(markdown), STREAM_CHUNK_SIZE):
        await msg.stream_token(markdown[start : start + STREAM_CHUNK_SIZE])
    await msg.update()


async def _send_welcome() -> None:
    await cl.Message(
        content=(
            "### Kumusta, Ka-Digisaka!\n\n"
            "Ako ang **AgriDataAgent**, katulong mo sa mabilis na paghanap ng impormasyon "
            "tungkol sa palay, presyo, ani, at mga balitang pang-agrikultura.\n\n"
            "Pwede kang magtanong nang simple, halimbawa:\n\n"
            "- **Presyo:** Magkano ang palay sa Nueva Ecija?\n"
            "- **Ani:** Kumusta ang average yield sa Laguna noong 2024?\n"
            "- **Balita:** May bagong balita ba tungkol sa rice farming?\n"
            "- **Gabay:** Ano ang gagawin kapag naninilaw ang dahon ng palay?\n\n"
            "Pumili sa starter cards sa ibaba o direktang mag-type ng tanong mo."
        )
    ).send()


async def _handle_text(text: str) -> None:
    command = apply_ui_command(
        text,
        current_mode=_mode(),
        current_source_ids=_source_ids(),
    )
    _set_mode(command.mode)
    _set_source_ids(command.source_ids)

    if command.notice:
        await cl.Message(content=command.notice).send()
    if not command.should_call_api:
        return

    payload = build_agent_payload(
        message=command.message,
        mode=command.mode,
        source_ids=command.source_ids,
        history=_history(),
    )
    try:
        async with cl.Step(name="Calling /v1/agent/chat", type="tool", show_input=True) as step:
            step.input = payload
            await step.stream_token("Sending request to AgriDataAgent API...\n")
            data = await _call_agent_api(payload)
            step.output = {
                "confidence": data.get("confidence"),
                "tool_calls": len(data.get("tool_calls") or []),
                "sources": len(data.get("sources") or []),
                "warnings": len(data.get("warnings") or []),
            }
    except httpx.HTTPStatusError as exc:
        await cl.Message(
            content=(
                f"Agent API returned HTTP {exc.response.status_code}. "
                "Check API auth, validation, or server logs."
            )
        ).send()
        return
    except Exception as exc:
        await cl.Message(
            content=(
                f"Could not reach the Agent API at `{_api_url()}` "
                f"(`{exc.__class__.__name__}`)."
            )
        ).send()
        return

    markdown = format_agent_response(data)
    await _stream_markdown(markdown)
    _set_history(
        [
            *_history(),
            {"role": "user", "content": command.message},
            {"role": "assistant", "content": str(data.get("answer") or "")},
        ][-10:]
    )


@cl.on_chat_start
async def on_chat_start() -> None:
    _set_history([])
    profile = cl.user_session.get("chat_profile")
    mode, source_ids = _profile_defaults(profile if isinstance(profile, str) else None)
    _set_mode(mode)
    _set_source_ids(source_ids)


@cl.on_message
async def on_message(message: cl.Message) -> None:
    await _handle_text(message.content)


@cl.on_chat_start
async def set_chat_profiles() -> list[cl.ChatProfile]:
    return [
        cl.ChatProfile(
            name=PROFILE_FARMER,
            display_name="Farmer Chat",
            icon="/public/AgriAgent.svg",
            markdown_description=(
                "### Kumusta, Ka-Digisaka!\n\n"
                "Magtanong tungkol sa presyo, ani, balita, o gabay sa palayan. "
                "Pumili ng halimbawa sa ibaba o direktang mag-type ng tanong."
            ),
            starters=[
                cl.Starter(
                    label="Nanilaw ang palay ko",
                    message=(
                        "/sources pinoyrice\n"
                        "Ano ang dapat gawin kapag naninilaw ang dahon ng palay?"
                    ),
                ),
                cl.Starter(
                    label="Bagong balita sa palay",
                    message=(
                        "/sources philrice_news,irri\n"
                        "May bagong balita ba tungkol sa palay at mga magsasaka?"
                    ),
                ),
                cl.Starter(
                    label="Magkano ang palay ngayon?",
                    message="Magkano palay ngayon?",
                ),
            ],
        ),
        cl.ChatProfile(
            name=PROFILE_DATA,
            display_name="Data Explorer",
            icon="/public/AgriAgent.svg",
            markdown_description=(
                "### Data Explorer\n\n"
                "Tingnan ang PRiSM yield, OpenSTAT prices, at source-backed agri corpus results."
            ),
            starters=[
                cl.Starter(
                    label="PRiSM yield",
                    message="Ano ang average yield ng palay sa Laguna 2 years ago?",
                ),
                cl.Starter(
                    label="OpenSTAT price",
                    message="Ano ang average farmgate price ng palay sa Nueva Ecija 3 years ago?",
                ),
                cl.Starter(
                    label="Latest IRRI news",
                    message=(
                        "/sources irri\n"
                        "Ano ang latest news sa IRRI tungkol sa rice farming?"
                    ),
                ),
            ],
        ),
        cl.ChatProfile(
            name=PROFILE_TASKLIST,
            display_name="Tasklist Planner",
            icon="/public/AgriAgent.svg",
            markdown_description=(
                "### Tasklist Planner\n\n"
                "Gumawa ng malinaw na checklist para sa scraper, corpus, indexing, at QA tasks."
            ),
            starters=[
                cl.Starter(
                    label="Corpus cleanup tasklist",
                    message="Gawan mo ako ng tasklist para linisin ang PhilRice News corpus",
                ),
                cl.Starter(
                    label="Scraper QA tasklist",
                    message="Gawan mo ako ng checklist para i-QA ang IRRI scraper outputs",
                ),
                cl.Starter(
                    label="Indexing tasklist",
                    message="Gawan mo ako ng tasklist para i-check ang Qdrant indexing readiness",
                ),
            ],
        ),
    ]
