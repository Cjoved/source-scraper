"""Lightweight farmer-facing intent and context inference."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

FarmerIntent = Literal[
    "price_query",
    "yield_query",
    "metadata_query",
    "news_query",
    "paper_query",
    "advisory_query",
    "unclear_query",
    "developer_task",
    "mixed",
]

FARMER_CORPUS_SOURCE_IDS = ("philrice_news", "irri", "philrice", "pinoyrice")
FARMER_NEWS_SOURCE_IDS = ("philrice_news", "irri")
FARMER_PAPER_SOURCE_IDS = ("philrice", "pinoyrice")


@dataclass(frozen=True)
class FarmerIntentResult:
    intent: FarmerIntent
    user_type: str
    language: str
    location: str | None
    crop: str | None
    missing_context: bool
    clarification_question: str | None
    recommended_source_ids: list[str] | None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _infer_mentioned_source_ids(message: str, intent: FarmerIntent) -> list[str] | None:
    """Narrow corpus scope when the user names PhilRice / IRRI / PinoyRice."""
    text = message.lower()
    wants_philrice = _has_any(text, ("philrice", "phil rice", "phil-rice"))
    wants_irri = re.search(r"\birri\b", text) is not None
    wants_pinoyrice = _has_any(text, ("pinoyrice", "pinoy rice", "pinoy-rice"))
    if not (wants_philrice or wants_irri or wants_pinoyrice):
        return None

    out: list[str] = []
    if intent == "news_query":
        if wants_philrice:
            out.append("philrice_news")
        if wants_irri:
            out.append("irri")
    elif intent == "paper_query":
        if wants_philrice:
            out.append("philrice")
        if wants_pinoyrice:
            out.append("pinoyrice")
        if wants_irri:
            out.append("irri")
    else:
        if wants_philrice:
            out.extend(["philrice_news", "philrice"])
        if wants_irri:
            out.append("irri")
        if wants_pinoyrice:
            out.append("pinoyrice")

    seen: set[str] = set()
    ordered: list[str] = []
    for source_id in out:
        if source_id not in seen:
            seen.add(source_id)
            ordered.append(source_id)
    return ordered or None


def _infer_language(message: str, language: str | None) -> str:
    explicit = _clean(language)
    if explicit:
        return explicit.lower()
    text = message.lower()
    tagalog_markers = (
        "ano",
        "magkano",
        "palay",
        "ani",
        "balita",
        "peste",
        "sakit",
        "tanim",
        "pataba",
        "bakit",
        "paano",
        "kailan",
        "petsa",
        "yung",
        "natin",
        "upload",
        "ni-upload",
        "na-upload",
        "may ",
        " ba",
        "ba?",
        "tayo",
        "meron",
        "regarding sa",
        "about sa",
    )
    return "taglish" if _has_any(text, tagalog_markers) else "en"


def is_taglish(language: str | None, message: str) -> bool:
    """True when reply should use Taglish based on explicit language or message markers."""
    lang = (language or "").lower()
    if lang in {"tl", "fil", "filipino", "tagalog", "taglish"} or lang.startswith("fil"):
        return True
    return _infer_language(message, None) == "taglish"


def infer_reply_language(
    message: str,
    explicit_language: str | None = None,
    session_language: str | None = None,
) -> str:
    """Prefer current message language over stale explicit/session language."""
    from_message = _infer_language(message, None)
    if from_message == "taglish":
        return "taglish"
    explicit = _clean(explicit_language)
    if explicit:
        return explicit.lower()
    session = _clean(session_language)
    if session:
        return session.lower()
    return from_message


def _infer_crop(message: str, crop: str | None) -> str | None:
    explicit = _clean(crop)
    if explicit:
        return explicit
    text = message.lower()
    if _has_any(text, ("palay", "rice", "bigas")):
        return "palay"
    if _has_any(text, ("mais", "corn")):
        return "corn"
    return None


def _classify_intent(message: str, user_type: str) -> FarmerIntent:
    text = message.lower()
    if user_type in {"developer", "admin"} or _has_any(
        text,
        ("api", "scraper", "qdrant", "implement", "debug", "testing", "unit test", "phase", "tasklist"),
    ):
        return "developer_task"
    if _has_any(
        text,
        ("crop", "crops", "commodit", "commodities", "produkto"),
    ) and _has_any(
        text,
        (
            "available",
            "meron",
            "list",
            "listahan",
            "anong",
            "ano ang",
            "what",
            "openstat",
            "datos",
            "data",
            "uri",
            "klase",
        ),
    ):
        return "metadata_query"
    if _has_any(text, ("magkano", "presyo", "price", "farmgate", "market price")):
        return "price_query"
    if _has_any(text, ("ani", "yield", "production", "mababa ani", "harvest")):
        return "yield_query"
    if _has_any(
        text,
        (
            "paper",
            "papers",
            "publication",
            "publications",
            "research",
            "study",
            "studies",
            "journal",
            "pdf",
            "document",
            "dokumento",
            "babasan",
            "babasahin",
        ),
    ):
        return "paper_query"
    if _has_any(text, ("balita", "news", "latest", "newest", "recent", "update")):
        return "news_query"
    if _has_any(
        text,
        (
            "sakit",
            "peste",
            "insekto",
            "dahon",
            "pataba",
            "fertilizer",
            "paano",
            "ano gagawin",
            "anong gagawin",
            "tanim",
            "pananim",
        ),
    ):
        return "advisory_query"
    return "unclear_query"


def _clarification(intent: FarmerIntent, *, location: str | None, crop: str | None) -> str | None:
    if intent == "price_query" and not location:
        return "Saang province o lugar mo gustong tingnan ang presyo?"
    if intent == "yield_query" and not location:
        return "Saang province o municipality mo gustong tingnan ang ani?"
    if intent == "advisory_query" and not crop:
        return "Palay ba ito, at anong stage na ng tanim?"
    if intent == "unclear_query":
        return "Ano ang gusto mong malaman: presyo, ani, balita, o problema sa tanim?"
    return None


def infer_farmer_intent(
    *,
    message: str,
    user_type: str | None,
    location: str | None,
    crop: str | None,
    language: str | None,
    source_ids: list[str] | None,
    session: object | None = None,
) -> FarmerIntentResult:
    from src.agent.follow_up import looks_like_corpus_continuation, looks_like_fresh_corpus_query
    from src.api.schemas import AgentSessionState

    resolved_user_type = (_clean(user_type) or "farmer").lower()
    resolved_location = _clean(location)
    resolved_crop = _infer_crop(message, crop)
    if isinstance(session, AgentSessionState):
        resolved_location = resolved_location or session.location
        resolved_crop = resolved_crop or session.crop
    intent = _classify_intent(message, resolved_user_type)

    if (
        intent == "unclear_query"
        and isinstance(session, AgentSessionState)
        and session.last_intent in {"news_query", "paper_query", "advisory_query"}
        and not looks_like_fresh_corpus_query(message)
        and len(message.split()) <= 15
    ):
        inherited = session.last_intent
        if inherited in {"price_query", "yield_query", "news_query", "paper_query", "advisory_query"}:
            intent = inherited  # type: ignore[assignment]

    clarification = _clarification(intent, location=resolved_location, crop=resolved_crop)
    mentioned = None if source_ids else _infer_mentioned_source_ids(message, intent)
    if intent == "news_query":
        recommended_source_ids = list(source_ids or mentioned or FARMER_NEWS_SOURCE_IDS)
    elif intent == "paper_query":
        recommended_source_ids = list(source_ids or mentioned or FARMER_PAPER_SOURCE_IDS)
    elif intent == "advisory_query":
        recommended_source_ids = list(source_ids or mentioned or FARMER_CORPUS_SOURCE_IDS)
    else:
        recommended_source_ids = None

    return FarmerIntentResult(
        intent=intent,
        user_type=resolved_user_type,
        language=_infer_language(message, language),
        location=resolved_location,
        crop=resolved_crop,
        missing_context=clarification is not None,
        clarification_question=clarification,
        recommended_source_ids=recommended_source_ids,
    )
