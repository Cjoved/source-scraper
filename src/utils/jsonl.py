"""JSONL file helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def append_jsonl(record: dict[str, Any], path: str | Path) -> None:
    """Append one JSON object as a line to a JSONL file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
