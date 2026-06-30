"""Plain-text file → CPT record list (shared by PhilRice News, IRRI, etc.)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.openstat.agri_corpus.cpt_utils import make_cpt_record
from src.utils.text_chunk import chunk_text


def text_to_cpt_records(
    text: str,
    *,
    source: str,
    base_id: str,
    min_chars: int,
    max_chars: int,
    **extra_kwargs: Any,
) -> list[dict]:
    """Build CPT records from cleaned text (optional chunking)."""
    text = (text or "").strip()
    if not text or len(text) < min_chars:
        return []

    url = extra_kwargs.get("url")
    title = extra_kwargs.get("title")
    filename = extra_kwargs.get("filename")
    page = extra_kwargs.get("page")
    url = url if isinstance(url, str) else None
    title = title if isinstance(title, str) else None
    filename = filename if isinstance(filename, str) else None
    page = page if isinstance(page, int) else None

    if max_chars > 0 and len(text) > max_chars:
        chunks = chunk_text(text, max_chars)
        records = []
        for j, ch in enumerate(chunks):
            if len(ch) < min_chars:
                continue
            records.append(
                make_cpt_record(
                    ch,
                    source,
                    f"{base_id}_chunk_{j}",
                    url=url,
                    title=title,
                    filename=filename,
                    page=page,
                )
            )
        return records

    return [
        make_cpt_record(
            text,
            source,
            base_id,
            url=url,
            title=title,
            filename=filename,
            page=page,
        )
    ]


def txt_file_to_cpt_records(
    path: Path,
    *,
    source: str,
    min_chars: int,
    max_chars: int,
    base_id_from: Callable[[Path, str], str],
    extra_fields: Callable[[Path], dict[str, Any]] | None = None,
    preprocess: Callable[[str], str] | None = None,
) -> list[dict]:
    """
    Read a .txt file, optionally chunk, and emit CPT records.

    ``base_id_from`` receives (path, full_text) and returns the base doc_id stem.
    ``extra_fields`` optionally returns kwargs passed to make_cpt_record (e.g. filename).
    ``preprocess`` may transform raw file text before chunking (IRRI cleaning, etc.).
    """
    if not path.is_file() or path.suffix.lower() != ".txt":
        return []
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except Exception:
        return []
    if not raw:
        return []

    text = preprocess(raw) if preprocess else raw
    base_id = base_id_from(path, raw)
    extra = extra_fields(path) if extra_fields else {}
    return text_to_cpt_records(
        text,
        source=source,
        base_id=base_id,
        min_chars=min_chars,
        max_chars=max_chars,
        **extra,
    )
