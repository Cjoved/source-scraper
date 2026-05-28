"""PhilRice PDF processing: data/philrice_pdfs → data/philrice_processed (per-file JSON + corpus JSONL)."""
import os
import re
import json
from pathlib import Path

from rich.console import Console
from dotenv import load_dotenv

from src.openstat.config import data_path, DATA_DIR
from src.openstat.agri_corpus.pdf_utils import (
    extract_text_from_pdf,
    detect_noise_lines,
    clean_pdf_text,
    HAS_PYMUPDF,
    HAS_PDFPLUMBER,
)
from src.openstat.agri_corpus.text_utils import chunk_text
from src.openstat.agri_corpus.cpt_utils import make_cpt_record

load_dotenv()
console = Console()

PHILRICE_PDFS_DIR = data_path("philrice_pdfs")
PHILRICE_PROCESSED_DIR = data_path("philrice_processed")
PHILRICE_PER_FILE_DIR = data_path("philrice_processed", "per_file")
OUTPUT_JSONL = data_path("philrice_processed", "philrice_corpus.jsonl")

CHUNK_BY_PAGE = True
MIN_CHUNK_CHARS = int(os.getenv("PHILRICE_MIN_CHUNK_CHARS", "100"))
MAX_CHUNK_CHARS = int(os.getenv("PHILRICE_MAX_CHUNK_CHARS", "0"))
DELETE_PDF_AFTER_CLEAN = os.getenv("PHILRICE_DELETE_PDF_AFTER_CLEAN", "").strip().lower() in ("true", "1", "yes")
SOURCE_NAME = "philrice"


def process_one_pdf(pdf_path: str, source_name: str = SOURCE_NAME) -> list[dict]:
    pages = extract_text_from_pdf(pdf_path)
    if not pages:
        return []
    noise_lines = detect_noise_lines(pages)
    if noise_lines:
        console.print(f"[dim]  Noise stripped ({len(noise_lines)} line/s): {sorted(noise_lines)[:3]}{'...' if len(noise_lines) > 3 else ''}[/dim]")
    records = []
    base_id = Path(pdf_path).stem
    fname = os.path.basename(pdf_path)
    for item in pages:
        page_num = item["page"]
        text = clean_pdf_text(item["text"], noise_lines)
        if len(text) < MIN_CHUNK_CHARS:
            continue
        if CHUNK_BY_PAGE and not MAX_CHUNK_CHARS:
            records.append(make_cpt_record(text, source_name, f"{base_id}_page_{page_num}", filename=fname, page=page_num))
        else:
            chunks = chunk_text(text, MAX_CHUNK_CHARS) if MAX_CHUNK_CHARS else [text]
            for j, ch in enumerate(chunks):
                if len(ch) < MIN_CHUNK_CHARS:
                    continue
                records.append(make_cpt_record(ch, source_name, f"{base_id}_page_{page_num}_chunk_{j}", filename=fname, page=page_num))
    return records


def run():
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
    os.makedirs(PHILRICE_PER_FILE_DIR, exist_ok=True)
    pdf_files = sorted(Path(PHILRICE_PDFS_DIR).glob("*.pdf"))
    if not pdf_files:
        console.print(f"[yellow]No PDFs in {PHILRICE_PDFS_DIR}[/yellow]")
        return
    console.rule("[bold cyan]PhilRice PDF processing")
    console.print(f"Processing {len(pdf_files)} PDFs → data/philrice_processed/")
    if DELETE_PDF_AFTER_CLEAN:
        console.print("[yellow]PHILRICE_DELETE_PDF_AFTER_CLEAN=true: PDFs will be deleted after processing.[/yellow]")
    total_records = 0
    with open(OUTPUT_JSONL, "w", encoding="utf-8") as corpus_f:
        for i, pdf_path in enumerate(pdf_files):
            path_str = str(pdf_path)
            console.print(f"[dim]({i + 1}/{len(pdf_files)}) {pdf_path.name}[/dim]")
            records = process_one_pdf(path_str)
            safe_stem = re.sub(r"[^\w\-.]", "_", pdf_path.stem)[:180]
            per_file_path = Path(PHILRICE_PER_FILE_DIR) / f"{safe_stem}.json"
            with open(per_file_path, "w", encoding="utf-8") as jf:
                json.dump(records, jf, ensure_ascii=False, indent=2)
            for r in records:
                corpus_f.write(json.dumps(r, ensure_ascii=False) + "\n")
            total_records += len(records)
            if DELETE_PDF_AFTER_CLEAN and path_str and os.path.isfile(path_str):
                try:
                    os.remove(path_str)
                    console.print(f"[dim]  Deleted: {pdf_path.name}[/dim]")
                except Exception as e:
                    console.print(f"[yellow]  Could not delete {pdf_path.name}: {e}[/yellow]")
    console.rule("[bold green]Done")
    console.print(f"Per-file JSON: [cyan]{PHILRICE_PER_FILE_DIR}[/cyan]")
    console.print(f"Corpus: [cyan]{OUTPUT_JSONL}[/cyan]")
    console.print(f"Total chunks: [green]{total_records}[/green]")
