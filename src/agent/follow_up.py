"""Session- and history-driven follow-up routing (not keyword-driven answers).

This module decides *when* to reuse prior context. The LLM in orchestrator decides
*what* the user means, using prior sources + conversation tail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.api.schemas import AgentChatMessage, AgentChatRequest, AgentSessionState, AgentSource

# Intents / tools that define an active conversation thread.
_CORPUS_INTENTS = frozenset({"news_query", "paper_query", "advisory_query"})
_DATA_INTENTS = frozenset({"price_query", "yield_query"})

# Only block obvious *new* corpus searches — not conversational follow-ups.
_FRESH_CORPUS_QUERY_MARKERS = (
    "latest news",
    "latest na",
    "bagong balita",
    "hanapin ang",
    "hanap ng",
    "search for",
    "find me",
    "list all",
    "ano ang latest",
    "ano yung latest",
    "ano yung ating latest",
)

CORPUS_SOURCE_IDS = frozenset(
    {
        "philrice_news",
        "irri",
        "philrice",
        "pinoyrice",
        "agri_corpus_rag",
    }
)

DATA_TOOLS = frozenset(
    {
        "summarize_prices",
        "search_prices",
        "summarize_yield",
        "search_yield_knowledge",
    }
)

_PRICE_TOOLS = frozenset({"summarize_prices", "search_prices"})
_YIELD_TOOLS = frozenset({"summarize_yield", "search_yield_knowledge"})

# Short follow-ups rarely exceed this; longer text is usually a new question.
_MAX_CONTINUATION_WORDS = 25

_ORDINAL_WORDS: dict[str, int] = {
    "una": 1,
    "unang": 1,
    "first": 1,
    "pangalawa": 2,
    "ikalawang": 2,
    "second": 2,
    "pangatlo": 3,
    "third": 3,
    "pangapat": 4,
    "fourth": 4,
    "panlima": 5,
    "fifth": 5,
}

_COUNT_WORDS: dict[str, int] = {
    "isa": 1,
    "isang": 1,
    "one": 1,
    "dalawa": 2,
    "two": 2,
    "tatlo": 3,
    "three": 3,
    "apat": 4,
    "four": 4,
    "lima": 5,
    "limang": 5,
    "five": 5,
}


@dataclass(frozen=True)
class CorpusFollowUp:
    sources: tuple[AgentSource, ...]


@dataclass(frozen=True)
class DataFollowUp:
    tool_name: str
    tool_args: dict[str, Any]


def prior_assistant_sources(history: list[AgentChatMessage]) -> list[AgentSource]:
    for item in reversed(history):
        if item.role == "assistant" and item.sources:
            return list(item.sources)
    return []


def looks_like_fresh_corpus_query(message: str) -> bool:
    text = message.lower()
    return any(marker in text for marker in _FRESH_CORPUS_QUERY_MARKERS)


def _word_count(message: str) -> int:
    return len(message.split())


def _has_corpus_session_context(session: AgentSessionState | None, prior: list[AgentSource]) -> bool:
    if _sources_look_corpus(prior):
        return True
    if session is None:
        return False
    if session.last_intent in _CORPUS_INTENTS:
        return True
    return session.last_tool_name == "search_corpus"


def _has_data_session_context(session: AgentSessionState | None) -> bool:
    if session is None:
        return False
    if session.last_intent in _DATA_INTENTS and session.last_tool_name in DATA_TOOLS:
        return True
    return session.last_tool_name in DATA_TOOLS


def _cross_domain_switch(message: str, session: AgentSessionState | None) -> bool:
    """User clearly switched topic (price ↔ news) — not a follow-up."""
    if session is None or not session.last_intent:
        return False
    text = message.lower()
    if session.last_intent in _CORPUS_INTENTS:
        return any(
            marker in text
            for marker in ("magkano", "presyo ng", "presyo sa", "farmgate", "yield sa", "ani sa")
        )
    if session.last_intent in _DATA_INTENTS:
        if looks_like_fresh_corpus_query(message):
            return True
        return any(marker in text for marker in ("balita", "news", "article", "paper", "publication"))
    return False


def looks_like_corpus_continuation(
    message: str,
    *,
    session: AgentSessionState | None,
    prior: list[AgentSource],
) -> bool:
    """Active corpus thread + prior sources + short message that is not a fresh search."""
    if not prior or not _has_corpus_session_context(session, prior):
        return False
    if looks_like_fresh_corpus_query(message):
        return False
    if _cross_domain_switch(message, session):
        return False
    text = message.strip()
    if not text:
        return False
    return _word_count(text) <= _MAX_CONTINUATION_WORDS


def looks_like_data_continuation(message: str, session: AgentSessionState | None) -> bool:
    """Reuse last price/yield tool when the user is still in the same data thread."""
    if not _has_data_session_context(session):
        return False
    if _cross_domain_switch(message, session):
        return False
    text = message.strip()
    if not text:
        return False
    return _word_count(text) <= _MAX_CONTINUATION_WORDS


def parse_source_indexes(message: str) -> list[int] | None:
    """Explicit 1-based indexes only (#2, no. 2, pangalawa) — user-named, not inferred."""
    text = message.lower()
    indexes: set[int] = set()
    for match in re.finditer(r"#(\d+)", text):
        indexes.add(int(match.group(1)))
    for match in re.finditer(r"\bno\.?\s*(\d+)\b", text):
        indexes.add(int(match.group(1)))
    for match in re.finditer(r"\bnumber\s+(\d+)\b", text):
        indexes.add(int(match.group(1)))
    for match in re.finditer(r"\barticle\s+(\d+)\b", text):
        indexes.add(int(match.group(1)))
    for word, index in _ORDINAL_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            indexes.add(index)
    if not indexes:
        return None
    return sorted(indexes)


def _parse_count_limit(message: str) -> int | None:
    text = message.lower()
    for word, count in _COUNT_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            return count
    return None


def resolve_referenced_sources(message: str, sources: list[AgentSource]) -> list[AgentSource]:
    """Apply only explicit user hints; let the LLM resolve ambiguous references."""
    if not sources:
        return []

    indexes = parse_source_indexes(message)
    if indexes:
        selected = [sources[index - 1] for index in indexes if 1 <= index <= len(sources)]
        if selected:
            return selected

    count_limit = _parse_count_limit(message)
    if count_limit is not None:
        return sources[: min(count_limit, len(sources))]

    return list(sources)


def conversation_tail_context(history: list[AgentChatMessage], *, max_turns: int = 4) -> str:
    if not history:
        return ""
    tail = history[-max_turns:]
    lines = ["Recent conversation (use this to infer what the user refers to):", ""]
    for item in tail:
        content = item.content.strip().replace("\n", " ")
        if len(content) > 320:
            content = content[:317] + "..."
        lines.append(f"- {item.role}: {content}")
    return "\n".join(lines)


def _sources_look_corpus(sources: list[AgentSource]) -> bool:
    for source in sources:
        source_id = (source.source_id or "").lower()
        if source_id in CORPUS_SOURCE_IDS:
            return True
        if source_id and "corpus" in source_id:
            return True
    return False


def _intent_family(intent: str) -> str | None:
    if intent in {"price_query", "mixed"}:
        return "price"
    if intent in {"yield_query"}:
        return "yield"
    if intent in {"news_query", "paper_query", "advisory_query"}:
        return "corpus"
    return None


def _tool_family(tool_name: str | None) -> str | None:
    if not tool_name:
        return None
    if tool_name in _PRICE_TOOLS:
        return "price"
    if tool_name in _YIELD_TOOLS:
        return "yield"
    if tool_name == "search_corpus":
        return "corpus"
    return None


def resolve_corpus_follow_up(
    body: AgentChatRequest,
    session: AgentSessionState | None = None,
) -> CorpusFollowUp | None:
    session = session or body.session_state
    prior = prior_assistant_sources(body.history)
    if not prior:
        return None
    if not looks_like_corpus_continuation(body.message, session=session, prior=prior):
        return None
    resolved = resolve_referenced_sources(body.message, prior)
    return CorpusFollowUp(sources=tuple(resolved))


def resolve_data_follow_up(
    body: AgentChatRequest,
    session: AgentSessionState | None,
    *,
    current_intent: str,
) -> DataFollowUp | None:
    session = session or body.session_state
    if session is None or not session.last_tool_name or not session.last_tool_args:
        return None
    if session.last_tool_name not in DATA_TOOLS:
        return None
    if not looks_like_data_continuation(body.message, session):
        return None

    current_family = _intent_family(current_intent)
    tool_family = _tool_family(session.last_tool_name)
    if current_family and tool_family and current_family != tool_family:
        return None

    return DataFollowUp(
        tool_name=session.last_tool_name,
        tool_args=dict(session.last_tool_args),
    )


def merge_data_follow_up_args(
    planned_args: dict[str, Any],
    follow_up: DataFollowUp,
) -> dict[str, Any]:
    merged = dict(follow_up.tool_args)
    merged.update(planned_args)
    return merged
