"""JSONL file helpers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from src.utils.text_sanitize import sanitize_corpus_text


def dumps_jsonl_record(record: dict[str, Any]) -> str:
    """Serialize one JSONL record as a single physical line (no embedded newlines)."""
    line = json.dumps(record, ensure_ascii=False)
    if "\n" in line or "\r" in line:
        raise ValueError("JSONL record must be a single line")
    return line


def append_jsonl(record: dict[str, Any], path: str | Path) -> None:
    """Append one JSON object as a line to a JSONL file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as f:
        f.write(dumps_jsonl_record(record) + "\n")


def _looks_like_new_record(line: str) -> bool:
    return line.startswith("{")


def iter_jsonl_records(path: str | Path) -> Iterator[tuple[int, dict[str, Any], int]]:
    """
    Yield (start_line, record, end_line) from a JSONL file.

    Buffers consecutive non-empty physical lines until one full JSON object is
    available. When a record is split across lines, continuation fragments do not
    start with ``{``; a successful early parse is ignored until the next line
    confirms a record boundary.
    """
    physical: list[tuple[int, str]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if stripped:
                physical.append((line_no, stripped))

    i = 0
    while i < len(physical):
        start_line, first = physical[i]
        buffer = first
        end_line = start_line
        j = i

        while True:
            try:
                obj = json.loads(buffer)
            except json.JSONDecodeError:
                obj = None

            has_next = j + 1 < len(physical)
            if obj is not None and isinstance(obj, dict):
                if not has_next:
                    yield start_line, obj, end_line
                    i = j + 1
                    break
                next_line = physical[j + 1][1]
                if _looks_like_new_record(next_line):
                    yield start_line, obj, end_line
                    i = j + 1
                    break

            if not has_next:
                if obj is None:
                    raise json.JSONDecodeError("Incomplete JSON at end of file", buffer, len(buffer))
                yield start_line, obj, end_line
                i = j + 1
                break

            j += 1
            end_line = physical[j][0]
            buffer += physical[j][1]


def _sanitize_record_for_write(record: dict[str, Any]) -> dict[str, Any]:
    out = dict(record)
    for key in ("text", "input", "content"):
        if key in out and isinstance(out[key], str):
            out[key] = sanitize_corpus_text(out[key])
    if (
        isinstance(out.get("text"), str)
        and isinstance(out.get("input"), str)
        and out["text"]
    ):
        out["input"] = out["text"]
        if "content" in out:
            out["content"] = out["text"]
    return out


def rewrite_jsonl_compact(path: str | Path, *, sanitize: bool = True) -> int:
    """Rewrite a JSONL file so each record occupies exactly one physical line."""
    src = Path(path)
    records = list(iter_jsonl_records(src))
    tmp = src.with_suffix(src.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        for _, record, _ in records:
            row = _sanitize_record_for_write(record) if sanitize else record
            handle.write(dumps_jsonl_record(row) + "\n")
    tmp.replace(src)
    return len(records)
