"""Normalize text for JSONL / embedding pipelines."""

from __future__ import annotations

import re

# Characters that are valid in JSON strings but break line-based tooling (splitlines).
_LINE_BREAK_CHARS = (
    "\u0085",  # NEL — common in PDF extraction
    "\u2028",  # LINE SEPARATOR
    "\u2029",  # PARAGRAPH SEPARATOR
    "\x0b",    # vertical tab
    "\x0c",    # form feed
)


def sanitize_corpus_text(text: str) -> str:
    """Replace PDF/Unicode line-break controls with spaces; keep normal newlines/tabs."""
    if not text:
        return ""
    for ch in _LINE_BREAK_CHARS:
        text = text.replace(ch, " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()
