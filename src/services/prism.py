"""PRISM corpus post-processing pipeline.

Reads raw PRISM JSONL corpus records and emits chunked CPT-style JSONL output.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from src.services.config import data_path
from src.utils.cpt import make_cpt_record
from src.utils.text_chunk import chunk_text
from src.utils.url_id import safe_id_from_url

load_dotenv()

console = Console()

PRISM_INPUT_JSONL = data_path("prism_processed", "prism_corpus.jsonl")
PRISM_OUTPUT_JSONL = data_path("prism_processed", "prism_corpus_chunked.jsonl")
SOURCE_NAME = "prism"
MIN_CHUNK_CHARS = int(os.getenv("PRISM_MIN_CHUNK_CHARS", "100"))
MAX_CHUNK_CHARS = int(os.getenv("PRISM_MAX_CHUNK_CHARS", "1800"))


def _iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                yield row


def run() -> None:
    console.rule("[bold cyan]Prism – Process[/bold cyan]")
    console.print(f"[dim]Input: {PRISM_INPUT_JSONL}[/dim]")
    console.print(f"[dim]Output: {PRISM_OUTPUT_JSONL}[/dim]")

    if not PRISM_INPUT_JSONL.is_file():
        console.print("[yellow]No prism_corpus.jsonl found; skipping process step.[/yellow]")
        return

    PRISM_OUTPUT_JSONL.parent.mkdir(parents=True, exist_ok=True)

    total_in = 0
    total_out = 0
    with PRISM_OUTPUT_JSONL.open("w", encoding="utf-8") as out:
        for idx, row in enumerate(_iter_jsonl(PRISM_INPUT_JSONL), start=1):
            total_in += 1
            text = str(row.get("text") or row.get("content") or row.get("input") or "").strip()
            if len(text) < MIN_CHUNK_CHARS:
                continue

            url = row.get("url")
            title = row.get("title")
            base_id = str(
                row.get("doc_id")
                or safe_id_from_url(str(url) if url else "", fallback=f"prism_{idx}")
            )
            chunks = chunk_text(text, MAX_CHUNK_CHARS)
            if not chunks:
                continue

            for j, chunk in enumerate(chunks):
                if len(chunk) < MIN_CHUNK_CHARS:
                    continue
                doc_id = base_id if len(chunks) == 1 else f"{base_id}_chunk_{j}"
                rec = make_cpt_record(
                    chunk,
                    SOURCE_NAME,
                    doc_id,
                    url=str(url) if url else None,
                    title=str(title) if title else None,
                )
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                total_out += 1

    console.print(f"[green]Processed records:[/green] {total_in}")
    console.print(f"[green]Chunked output rows:[/green] {total_out}")


if __name__ == "__main__":
    run()

