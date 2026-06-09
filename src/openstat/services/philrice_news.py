"""PhilRice News .txt → CPT JSON. Input: data/philrice_news/*.txt → data/philrice_news_processed/."""
import json
import os
import re
from pathlib import Path

from rich.console import Console
from dotenv import load_dotenv

from src.openstat.agri_corpus.txt_cpt import txt_file_to_cpt_records
from src.openstat.config import data_path
from src.utils.jsonl import dumps_jsonl_record

load_dotenv()
console = Console()

PHILRICE_NEWS_DIR = data_path("philrice_news")
PHILRICE_NEWS_PROCESSED_DIR = data_path("philrice_news_processed")
PHILRICE_NEWS_PER_FILE_DIR = data_path("philrice_news_processed", "per_file")
OUTPUT_JSONL = data_path("philrice_news_processed", "philrice_news_corpus.jsonl")

SOURCE_NAME = "philrice_news"
MIN_CHUNK_CHARS = int(os.getenv("PHILRICE_NEWS_MIN_CHUNK_CHARS", "100"))
MAX_CHUNK_CHARS = int(os.getenv("PHILRICE_NEWS_MAX_CHUNK_CHARS", "0"))


def _base_id_from_path(path: Path, _text: str) -> str:
    stem = path.stem
    return re.sub(r"[^\w\-.]", "_", stem)[:120] or "philrice_news_unknown"


def _extra_fields(path: Path) -> dict:
    return {"filename": path.name}


def txt_to_cpt_records(txt_path: str) -> list[dict]:
    return txt_file_to_cpt_records(
        Path(txt_path),
        source=SOURCE_NAME,
        min_chars=MIN_CHUNK_CHARS,
        max_chars=MAX_CHUNK_CHARS,
        base_id_from=_base_id_from_path,
        extra_fields=_extra_fields,
    )


def run():
    if not os.path.isdir(PHILRICE_NEWS_DIR):
        console.print(f"[yellow]Folder not found: {PHILRICE_NEWS_DIR}[/yellow]")
        console.print("[dim]Run PhilRice News scraper first.[/dim]")
        return
    os.makedirs(PHILRICE_NEWS_PER_FILE_DIR, exist_ok=True)
    txt_files = sorted(Path(PHILRICE_NEWS_DIR).glob("*.txt"))
    if not txt_files:
        console.print(f"[yellow]No .txt files in {PHILRICE_NEWS_DIR}[/yellow]")
        return
    console.rule("[bold cyan]PhilRice News .txt → CPT JSON[/bold cyan]")
    console.print(f"Processing {len(txt_files)} files → {OUTPUT_JSONL}")
    total = 0
    with open(OUTPUT_JSONL, "w", encoding="utf-8", newline="\n") as corpus_f:
        for i, txt_path in enumerate(txt_files):
            records = txt_to_cpt_records(str(txt_path))
            if not records:
                continue
            console.print(f"[dim]({i + 1}/{len(txt_files)}) {txt_path.name} → {len(records)} chunk(s)[/dim]")
            per_file_path = Path(PHILRICE_NEWS_PER_FILE_DIR) / f"{txt_path.stem}.json"
            with open(per_file_path, "w", encoding="utf-8") as jf:
                json.dump(records, jf, ensure_ascii=False, indent=2)
            for r in records:
                corpus_f.write(dumps_jsonl_record(r) + "\n")
                total += 1
    console.print(f"[green]Done. Total CPT records: {total}[/green]")
