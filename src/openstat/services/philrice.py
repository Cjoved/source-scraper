"""PhilRice PDF processing: data/philrice_pdfs → data/philrice_processed (per-file JSON + corpus JSONL)."""
import json
import os
import re
from pathlib import Path
from typing import TextIO

from dotenv import load_dotenv
from rich.console import Console

from src.openstat.agri_corpus.cpt_utils import make_cpt_record
from src.openstat.agri_corpus.pdf_utils import (
    HAS_PDFPLUMBER,
    HAS_PYMUPDF,
    clean_pdf_text,
    detect_noise_lines,
    extract_text_from_pdf,
)
from src.openstat.agri_corpus.text_utils import chunk_text
from src.openstat.config import data_path
from src.utils.jsonl import dumps_jsonl_record

load_dotenv()
console = Console()

PHILRICE_PDFS_DIR = data_path("philrice_pdfs")
PHILRICE_PROCESSED_DIR = data_path("philrice_processed")
PHILRICE_PER_FILE_DIR = data_path("philrice_processed", "per_file")
OUTPUT_JSONL = data_path("philrice_processed", "philrice_corpus.jsonl")

CHUNK_BY_PAGE = True
MIN_CHUNK_CHARS = int(os.getenv("PHILRICE_MIN_CHUNK_CHARS", "100"))
MAX_CHUNK_CHARS = int(os.getenv("PHILRICE_MAX_CHUNK_CHARS", "0"))
SOURCE_NAME = "philrice"


def stream_process_enabled() -> bool:
    return os.getenv("PHILRICE_STREAM_PROCESS", "true").strip().lower() in ("true", "1", "yes")


def write_per_file_enabled() -> bool:
    return os.getenv("PHILRICE_WRITE_PER_FILE", "false").strip().lower() in ("true", "1", "yes")


def delete_pdf_after_process() -> bool:
    raw = os.getenv("PHILRICE_DELETE_PDF_AFTER_CLEAN", "").strip().lower()
    if raw in ("false", "0", "no"):
        return False
    if raw in ("true", "1", "yes"):
        return True
    # Unset: default on in stream mode (VPS disk), off in batch unless explicitly set
    return stream_process_enabled()


def process_one_pdf(pdf_path: str, source_name: str = SOURCE_NAME) -> list[dict]:
    pages = extract_text_from_pdf(pdf_path)
    if not pages:
        return []
    noise_lines = detect_noise_lines(pages)
    if noise_lines:
        console.print(
            f"[dim]  Noise stripped ({len(noise_lines)} line/s): {sorted(noise_lines)[:3]}"
            f"{'...' if len(noise_lines) > 3 else ''}[/dim]"
        )
    records = []
    base_id = Path(pdf_path).stem
    fname = os.path.basename(pdf_path)
    for item in pages:
        page_num = item["page"]
        text = clean_pdf_text(item["text"], noise_lines)
        if len(text) < MIN_CHUNK_CHARS:
            continue
        if CHUNK_BY_PAGE and not MAX_CHUNK_CHARS:
            records.append(
                make_cpt_record(
                    text, source_name, f"{base_id}_page_{page_num}", filename=fname, page=page_num
                )
            )
        else:
            chunks = chunk_text(text, MAX_CHUNK_CHARS) if MAX_CHUNK_CHARS else [text]
            for j, ch in enumerate(chunks):
                if len(ch) < MIN_CHUNK_CHARS:
                    continue
                records.append(
                    make_cpt_record(
                        ch,
                        source_name,
                        f"{base_id}_page_{page_num}_chunk_{j}",
                        filename=fname,
                        page=page_num,
                    )
                )
    return records


def _write_per_file_json(pdf_path: str, records: list[dict]) -> None:
    os.makedirs(PHILRICE_PER_FILE_DIR, exist_ok=True)
    safe_stem = re.sub(r"[^\w\-.]", "_", Path(pdf_path).stem)[:180]
    per_file_path = Path(PHILRICE_PER_FILE_DIR) / f"{safe_stem}.json"
    with open(per_file_path, "w", encoding="utf-8") as jf:
        json.dump(records, jf, ensure_ascii=False, indent=2)


def ingest_pdf_to_corpus(
    pdf_path: str,
    corpus_f: TextIO,
    *,
    delete_after: bool | None = None,
) -> int:
    """
    Extract one PDF, append CPT records to corpus_f, optionally delete PDF from disk.
    Returns number of records written.
    """
    path_str = str(pdf_path)
    console.print(f"[dim]  Processing: {os.path.basename(path_str)}[/dim]")
    records = process_one_pdf(path_str)
    if write_per_file_enabled() and records:
        _write_per_file_json(path_str, records)
    for record in records:
        corpus_f.write(dumps_jsonl_record(record) + "\n")
    corpus_f.flush()
    n = len(records)
    if n:
        console.print(f"[green]  +{n} corpus record(s)[/green]")
    else:
        console.print("[yellow]  No text extracted (skipped).[/yellow]")

    should_delete = delete_pdf_after_process() if delete_after is None else delete_after
    if should_delete and os.path.isfile(path_str):
        try:
            os.remove(path_str)
            console.print(f"[dim]  Deleted PDF: {os.path.basename(path_str)}[/dim]")
        except OSError as exc:
            console.print(f"[yellow]  Could not delete {os.path.basename(path_str)}: {exc}[/yellow]")
    return n


def open_corpus_for_stream(*, fresh: bool | None = None) -> tuple[TextIO, str]:
    """Open philrice_corpus.jsonl for append (stream) or truncate (fresh run)."""
    os.makedirs(PHILRICE_PROCESSED_DIR, exist_ok=True)
    if fresh is None:
        fresh = os.getenv("PHILRICE_FRESH_CORPUS", "false").strip().lower() in ("true", "1", "yes")
    path = OUTPUT_JSONL
    if fresh or not os.path.isfile(path) or os.path.getsize(path) == 0:
        mode = "w"
        console.print(f"[dim]Corpus output (new): {path}[/dim]")
    else:
        mode = "a"
        console.print(f"[dim]Corpus output (append): {path}[/dim]")
    return open(path, mode, encoding="utf-8", newline="\n"), path


def run(*, append_corpus: bool = False) -> None:
    """Batch process: all PDFs in philrice_pdfs/ (used when PHILRICE_STREAM_PROCESS=false or leftovers)."""
    if not HAS_PYMUPDF:
        console.print("[red]Install PyMuPDF first: pip install pymupdf[/red]")
        return
    if HAS_PDFPLUMBER:
        console.print("[dim]Table extraction enabled (pdfplumber).[/dim]")
    else:
        console.print("[dim]Install pdfplumber for table extraction.[/dim]")
    if not os.path.isdir(PHILRICE_PDFS_DIR):
        console.print(f"[yellow]Folder not found: {PHILRICE_PDFS_DIR}[/yellow]")
        console.print("[dim]Run PhilRice scraper first to download PDFs.[/dim]")
        return
    pdf_files = sorted(Path(PHILRICE_PDFS_DIR).glob("*.pdf"))
    if not pdf_files:
        console.print(f"[yellow]No PDFs in {PHILRICE_PDFS_DIR}[/yellow]")
        return
    console.rule("[bold cyan]PhilRice PDF processing (batch)")
    console.print(f"Processing {len(pdf_files)} PDFs → data/philrice_processed/")
    if delete_pdf_after_process():
        console.print("[yellow]PHILRICE_DELETE_PDF_AFTER_CLEAN=true: PDFs will be deleted after processing.[/yellow]")
    corpus_mode = "a" if append_corpus and os.path.isfile(OUTPUT_JSONL) else "w"
    if corpus_mode == "a":
        console.print(f"[dim]Appending leftovers to corpus: {OUTPUT_JSONL}[/dim]")
    total_records = 0
    with open(OUTPUT_JSONL, corpus_mode, encoding="utf-8", newline="\n") as corpus_f:
        for i, pdf_path in enumerate(pdf_files):
            console.print(f"[dim]({i + 1}/{len(pdf_files)}) {pdf_path.name}[/dim]")
            total_records += ingest_pdf_to_corpus(str(pdf_path), corpus_f)
    console.rule("[bold green]Done")
    console.print(f"Corpus: [cyan]{OUTPUT_JSONL}[/cyan]")
    console.print(f"Total chunks: [green]{total_records}[/green]")
    if write_per_file_enabled():
        console.print(f"Per-file JSON: [cyan]{PHILRICE_PER_FILE_DIR}[/cyan]")
