"""RAG corpus source manifest (P3.8a).

Single source of truth for JSONL paths indexed into ``agri_corpus_rag``.
Validation imports these entries plus extra non-RAG sources in
``validate_corpus.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.services.config import data_path

DEFAULT_CORPUS_RAG_COLLECTION = "agri_corpus_rag"


@dataclass(frozen=True)
class RagCorpusSource:
    """One JSONL file indexed into the unified RAG collection."""

    source_id: str
    relpath: str
    description: str = ""
    required: bool = True
    # Per-source min text length when --quality; None = VALIDATE_MIN_TEXT_CHARS.
    min_text_chars: int | None = None


RAG_CORPUS_SOURCES: tuple[RagCorpusSource, ...] = (
    RagCorpusSource(
        "philrice",
        "philrice_processed/philrice_corpus.jsonl",
        "PhilRice PDF",
        min_text_chars=80,
    ),
    RagCorpusSource(
        "philrice_news",
        "philrice_news_processed/philrice_news_corpus.jsonl",
        "PhilRice News",
    ),
    RagCorpusSource(
        "pinoyrice",
        "pinoyrice_processed/pinoyrice_corpus.jsonl",
        "PinoyRice text",
    ),
    RagCorpusSource(
        "irri",
        "irri_processed/irri_corpus.jsonl",
        "IRRI Philippines",
    ),
    RagCorpusSource(
        "prism_browser",
        "prism_processed/prism_corpus_chunked.jsonl",
        "PRiSM browser chunked",
        required=False,
    ),
)

RAG_SOURCE_BY_ID: dict[str, RagCorpusSource] = {s.source_id: s for s in RAG_CORPUS_SOURCES}


def rag_source_path(source: RagCorpusSource) -> Path:
    """Resolve a manifest entry to an absolute path under ``data/``."""
    return data_path(*source.relpath.split("/"))


def resolve_rag_sources(
    *,
    source_filter: str | None = None,
) -> list[tuple[RagCorpusSource, Path]]:
    """Return manifest entries with resolved paths, optionally filtered by id."""
    selected = RAG_CORPUS_SOURCES
    if source_filter:
        if source_filter not in RAG_SOURCE_BY_ID:
            known = ", ".join(RAG_SOURCE_BY_ID)
            raise ValueError(f"Unknown RAG source id '{source_filter}'. Known: {known}")
        selected = (RAG_SOURCE_BY_ID[source_filter],)
    return [(spec, rag_source_path(spec)) for spec in selected]
