"""Shared Facebook feed heuristics (Playwright + HTML parsers)."""

from __future__ import annotations

import re

_OTHER_POSTS_LABELS = ("Other posts", "Mga ibang post", "Autres publications")

_SIDEBAR_MARKERS = (
    "communities",
    "subscriber hub",
    "personal details",
    "see all photos",
    "lives in ",
    "from talavera",
    "wesleyan university",
)

_COMMENT_UI_MARKERS = (
    "write a comment",
    "write a public comment",
    "comment as ",
    "add a comment",
)

# Reply-only: "First Last\nShort sentence..." without post headline signals
_REPLY_NAME_LINE = re.compile(
    r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\s*\n.{10,120}$",
    re.MULTILINE,
)

_RELATIVE_TIME_TEXT = re.compile(
    r"^(\d+[hdmws]|"
    r"\d+\s*(min|mins|minutes?|hr|hrs|hours?|day|days?)|"
    r"(just now|yesterday)|"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b)",
    re.I,
)

_STORY_TEXT_HINT = re.compile(
    r"(#\w+|P\s?\d[\d,]+|palay|dswd|pinansyal|tulong|magsasaka|presyo)",
    re.I,
)


def other_posts_labels() -> tuple[str, ...]:
    return _OTHER_POSTS_LABELS


def is_sidebar_noise(text: str) -> bool:
    lower = text.lower()[:500]
    return any(marker in lower for marker in _SIDEBAR_MARKERS)


def is_pinned_article_text(text: str) -> bool:
    lower = text.lower()
    if lower.startswith("pinned post"):
        return True
    lines = [ln.strip().lower() for ln in text.splitlines() if ln.strip()]
    return bool(lines and lines[0] == "pinned post")


def is_comment_ui_article(text: str) -> bool:
    lower = text.lower()
    if any(marker in lower for marker in _COMMENT_UI_MARKERS):
        return True
    if _REPLY_NAME_LINE.match(text.strip()):
        return True
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) == 2 and len(lines[1]) < 120 and "#" not in text:
        first, second = lines[0], lines[1]
        if " " in first and not first.lower().startswith("pinned"):
            return True
    return False


def feed_start_index(has_pinned_label: bool, *, skip_pinned: bool = True) -> int:
    if skip_pinned and has_pinned_label:
        return 1
    return 0


def looks_like_relative_time(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned or len(cleaned) > 40:
        return False
    return bool(_RELATIVE_TIME_TEXT.search(cleaned))


def has_story_text_signals(text: str) -> bool:
    return bool(_STORY_TEXT_HINT.search(text))
