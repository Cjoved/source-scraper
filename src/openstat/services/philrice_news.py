"""PhilRice News -> CPT JSONL (stream or batch)."""
from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from pathlib import Path
from typing import TextIO

from rich.console import Console
from dotenv import load_dotenv

from src.openstat.agri_corpus.text_utils import chunk_text
from src.openstat.agri_corpus.cpt_utils import make_cpt_record
from src.openstat.config import data_path
from src.utils.jsonl import dumps_jsonl_record

load_dotenv()
console = Console()

PHILRICE_NEWS_DIR = data_path("philrice_news")
PHILRICE_NEWS_PROCESSED_DIR = data_path("philrice_news_processed")
OUTPUT_JSONL = data_path("philrice_news_processed", "philrice_news_corpus.jsonl")

SOURCE_NAME = "philrice_news"
MIN_CHUNK_CHARS = int(os.getenv("PHILRICE_NEWS_MIN_CHUNK_CHARS", "100"))
MAX_CHUNK_CHARS = int(os.getenv("PHILRICE_NEWS_MAX_CHUNK_CHARS", "0"))


def stream_process_enabled() -> bool:
    return os.getenv("PHILRICE_NEWS_STREAM_PROCESS", "true").strip().lower() in ("true", "1", "yes")


def delete_txt_after_process() -> bool:
    raw = os.getenv("PHILRICE_NEWS_DELETE_TXT_AFTER_PROCESS", "").strip().lower()
    if raw in ("false", "0", "no"):
        return False
    if raw in ("true", "1", "yes"):
        return True
    return stream_process_enabled()


def _base_id_from_stem(stem: str) -> str:
    return re.sub(r"[^\w\-.]", "_", stem)[:120] or "philrice_news_unknown"


def _url_slug_for_id(url: str, max_len: int = 48) -> str:
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        path = (parsed.path or "").strip("/")
        if not path:
            return ""
        slug = path.split("/")[-1].strip()
        if not slug:
            return ""
        slug = re.sub(r"[^\w\-]", "_", slug.lower())
        slug = re.sub(r"_+", "_", slug).strip("_")
        digest = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:8]
        return f"{slug[:max_len]}_{digest}"
    except Exception:
        return ""


def _title_from_filename_stem(stem: str) -> str:
    """Best-effort title from ``{title}_{YYYY-MM-DD}`` stem."""
    m = re.match(r"^(.+)_(\d{4}-\d{2}-\d{2})(?:_\d+)?$", stem)
    if m:
        return m.group(1).replace("_", " ").strip()
    return stem.replace("_", " ").strip() or stem


def article_to_cpt_records(
    url: str,
    title: str,
    body: str,
    filename: str,
) -> list[dict]:
    text = (body or "").strip()
    if not text or len(text) < MIN_CHUNK_CHARS:
        return []
    stem = Path(filename).stem if filename else _base_id_from_stem(title or "article")
    base_id = _base_id_from_stem(stem)
    url_slug = _url_slug_for_id(url)
    if url_slug and not base_id.endswith(url_slug):
        base_id = f"{base_id}_{url_slug}"
    chunks = chunk_text(text, MAX_CHUNK_CHARS) if MAX_CHUNK_CHARS and MAX_CHUNK_CHARS > 0 else [text]
    out: list[dict] = []
    clean_title = (title or "").strip() or _title_from_filename_stem(stem)
    fname = filename or f"{stem}.txt"
    for idx, ch in enumerate(chunks):
        if len(ch) < MIN_CHUNK_CHARS:
            continue
        doc_id = base_id if len(chunks) == 1 else f"{base_id}_chunk_{idx}"
        out.append(
            make_cpt_record(
                ch,
                SOURCE_NAME,
                doc_id,
                url=url or None,
                title=clean_title or None,
                filename=fname,
            )
        )
    return out


def open_corpus_for_stream(*, fresh: bool | None = None) -> tuple[TextIO, str]:
    """Open philrice_news_corpus.jsonl for append (stream) or truncate (fresh run)."""
    os.makedirs(PHILRICE_NEWS_PROCESSED_DIR, exist_ok=True)
    if fresh is None:
        fresh = os.getenv("PHILRICE_NEWS_FRESH_CORPUS", "false").strip().lower() in ("true", "1", "yes")
    if fresh or not os.path.isfile(OUTPUT_JSONL) or os.path.getsize(OUTPUT_JSONL) == 0:
        mode = "w"
        console.print(f"[dim]Corpus output (new): {OUTPUT_JSONL}[/dim]")
    else:
        mode = "a"
        console.print(f"[dim]Corpus output (append): {OUTPUT_JSONL}[/dim]")
    return open(OUTPUT_JSONL, mode, encoding="utf-8", newline="\n"), OUTPUT_JSONL


def ingest_article_to_corpus(
    url: str,
    title: str,
    body: str,
    filename: str,
    corpus_f: TextIO,
) -> int:
    """Clean one scraped article and append CPT chunks."""
    records = article_to_cpt_records(url, title, body, filename)
    for record in records:
        corpus_f.write(dumps_jsonl_record(record) + "\n")
    corpus_f.flush()
    n = len(records)
    if n:
        console.print(f"[green]  +{n} corpus record(s)[/green]")
    return n


def ingest_txt_to_corpus(
    txt_path: str,
    corpus_f: TextIO,
    *,
    url: str | None = None,
    title: str | None = None,
    delete_after: bool | None = None,
) -> int:
    """Read one .txt (body-only legacy file), append CPT records, optionally delete."""
    path = Path(txt_path)
    if not path.is_file():
        return 0
    try:
        body = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        console.print(f"[yellow]Read failed {path.name}: {exc}[/yellow]")
        return 0
    if not body:
        return 0
    stem = path.stem
    resolved_title = (title or "").strip() or _title_from_filename_stem(stem)
    resolved_url = (url or "").strip()
    records = article_to_cpt_records(resolved_url, resolved_title, body, path.name)
    for record in records:
        corpus_f.write(dumps_jsonl_record(record) + "\n")
    corpus_f.flush()
    n = len(records)
    if n:
        console.print(f"[green]  +{n} corpus record(s) from {path.name}[/green]")
    should_delete = delete_txt_after_process() if delete_after is None else delete_after
    if should_delete and path.is_file():
        try:
            path.unlink()
            console.print(f"[dim]  Deleted .txt: {path.name}[/dim]")
        except OSError as exc:
            console.print(f"[yellow]  Could not delete {path.name}: {exc}[/yellow]")
    return n


def run_batch_rewrite() -> int:
    """Batch mode: rewrite corpus from all .txt files on disk."""
    if not os.path.isdir(PHILRICE_NEWS_DIR):
        console.print(f"[yellow]Folder not found: {PHILRICE_NEWS_DIR}[/yellow]")
        console.print("[dim]Run PhilRice News scraper first.[/dim]")
        return 0
    txt_files = sorted(Path(PHILRICE_NEWS_DIR).glob("*.txt"))
    if not txt_files:
        console.print(f"[yellow]No .txt files in {PHILRICE_NEWS_DIR}[/yellow]")
        return 0
    console.rule("[bold cyan]PhilRice News .txt -> CPT JSON[/bold cyan]")
    console.print(f"Processing {len(txt_files)} files -> {OUTPUT_JSONL}")
    total = 0
    with open(OUTPUT_JSONL, "w", encoding="utf-8", newline="\n") as corpus_f:
        for i, txt_path in enumerate(txt_files):
            n = ingest_txt_to_corpus(str(txt_path), corpus_f, delete_after=False)
            if not n:
                continue
            if (i + 1) % 50 == 0 or i == 0 or i + 1 == len(txt_files):
                console.print(f"[dim]({i + 1}/{len(txt_files)}) {txt_path.name} -> {n} chunk(s)[/dim]")
            total += n
    console.print(f"[green]Done. Total CPT records: {total}[/green]")
    return total


def run_leftovers(
    *,
    url_to_file: dict[str, str] | None = None,
    url_to_title: dict[str, str] | None = None,
) -> int:
    """Process leftover .txt after stream scrape (migration from batch runs)."""
    news_dir = Path(PHILRICE_NEWS_DIR)
    if not news_dir.is_dir():
        console.print("[dim]Stream mode: no philrice_news folder.[/dim]")
        return 0
    txt_files = sorted(news_dir.glob("*.txt"))
    if not txt_files:
        console.print("[dim]Stream mode: no leftover PhilRice News .txt files.[/dim]")
        return 0

    file_to_url: dict[str, str] = {}
    if url_to_file:
        file_to_url = {fname: u for u, fname in url_to_file.items()}

    console.rule("[bold cyan]PhilRice News leftovers (stream cleanup)[/bold cyan]")
    console.print(f"Processing {len(txt_files)} leftover .txt -> {OUTPUT_JSONL}")
    total = 0
    os.makedirs(PHILRICE_NEWS_PROCESSED_DIR, exist_ok=True)
    fresh = os.getenv("PHILRICE_NEWS_FRESH_CORPUS", "false").strip().lower() in ("true", "1", "yes")
    mode = "w" if fresh or not os.path.isfile(OUTPUT_JSONL) or os.path.getsize(OUTPUT_JSONL) == 0 else "a"
    if mode == "w":
        console.print(f"[dim]Corpus output (new / fresh): {OUTPUT_JSONL}[/dim]")
    with open(OUTPUT_JSONL, mode, encoding="utf-8", newline="\n") as corpus_f:
        for txt_path in txt_files:
            url = file_to_url.get(txt_path.name, "")
            title = ""
            if url and url_to_title:
                title = url_to_title.get(url, "")
            total += ingest_txt_to_corpus(
                str(txt_path),
                corpus_f,
                url=url or None,
                title=title or None,
                delete_after=True,
            )
    console.print(f"Leftover CPT records: [green]{total}[/green]")
    return total


def run(*, leftovers_only: bool | None = None) -> None:
    os.makedirs(PHILRICE_NEWS_PROCESSED_DIR, exist_ok=True)
    if leftovers_only is None:
        leftovers_only = stream_process_enabled()
    if leftovers_only:
        from src.openstat.scrapers.philrice_news import _load_checkpoint_state

        _, url_to_file, _, url_to_title = _load_checkpoint_state()
        run_leftovers(url_to_file=url_to_file, url_to_title=url_to_title)
        return
    run_batch_rewrite()


if __name__ == "__main__":
    run()
