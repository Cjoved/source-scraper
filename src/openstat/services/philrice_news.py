"""PhilRice News .txt → CPT JSON. Input: data/philrice_news/*.txt → data/philrice_news_processed/."""
import os
import re
import json
from pathlib import Path

from rich.console import Console
from dotenv import load_dotenv

from src.openstat.config import data_path
from src.openstat.agri_corpus.text_utils import chunk_text
from src.openstat.agri_corpus.cpt_utils import make_cpt_record

load_dotenv()
console = Console()

PHILRICE_NEWS_DIR = data_path("philrice_news")
PHILRICE_NEWS_PROCESSED_DIR = data_path("philrice_news_processed")
PHILRICE_NEWS_PER_FILE_DIR = data_path("philrice_news_processed", "per_file")
OUTPUT_JSONL = data_path("philrice_news_processed", "philrice_news_corpus.jsonl")

SOURCE_NAME = "philrice_news"
MIN_CHUNK_CHARS = int(os.getenv("PHILRICE_NEWS_MIN_CHUNK_CHARS", "100"))
MAX_CHUNK_CHARS = int(os.getenv("PHILRICE_NEWS_MAX_CHUNK_CHARS", "0"))


def txt_to_cpt_records(txt_path: str) -> list[dict]:
    path = Path(txt_path)
    if not path.is_file() or path.suffix.lower() != ".txt":
        return []
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception as e:
        console.print(f"[yellow]Read failed {path.name}: {e}[/yellow]")
        return []
    if not text:
        return []
    stem = path.stem
    base_id = re.sub(r"[^\w\-.]", "_", stem)[:120] or "philrice_news_unknown"
    if MAX_CHUNK_CHARS > 0 and len(text) > MAX_CHUNK_CHARS:
        chunks = chunk_text(text, MAX_CHUNK_CHARS)
        records = []
        for j, ch in enumerate(chunks):
            if len(ch) < MIN_CHUNK_CHARS:
                continue
            records.append(make_cpt_record(ch, SOURCE_NAME, f"{base_id}_chunk_{j}", filename=path.name))
        return records
    if len(text) < MIN_CHUNK_CHARS:
        return []
    return [make_cpt_record(text, SOURCE_NAME, base_id, filename=path.name)]


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
    console.rule("[bold cyan]PhilRice News .txt -> CPT JSON")
    console.print(f"Processing {len(txt_files)} .txt files → data/philrice_news_processed/")
    total = 0
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as corpus_f:
        for i, txt_path in enumerate(txt_files):
            records = txt_to_cpt_records(str(txt_path))
            if not records:
                continue
            console.print(f"[dim]({i + 1}/{len(txt_files)}) {txt_path.name} -> {len(records)} chunk(s)[/dim]")
            safe_stem = re.sub(r"[^\w\-.]", "_", txt_path.stem)[:180]
            per_file_path = Path(PHILRICE_NEWS_PER_FILE_DIR) / f"{safe_stem}.json"
            with open(per_file_path, "w", encoding="utf-8") as jf:
                json.dump(records, jf, ensure_ascii=False, indent=2)
            for r in records:
                corpus_f.write(json.dumps(r, ensure_ascii=False) + "\n")
            total += len(records)
    console.rule("[bold green]Done")
    console.print(f"Total CPT records: [green]{total}[/green]")
