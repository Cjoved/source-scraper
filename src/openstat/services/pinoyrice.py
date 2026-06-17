"""PinoyRice processing: text + PDFs -> CPT JSONL (stream or batch)."""
import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import TextIO

from rich.console import Console
from dotenv import load_dotenv

from src.openstat.config import data_path
from src.openstat.agri_corpus.text_utils import chunk_text, safe_id_from_url
from src.openstat.agri_corpus.pdf_utils import (
    extract_text_from_pdf,
    detect_noise_lines,
    clean_pdf_text,
    HAS_PYMUPDF,
)
from src.openstat.agri_corpus.cpt_utils import make_cpt_record
from src.utils.jsonl import dumps_jsonl_record

load_dotenv()
console = Console()

PINOYRICE_PROCESSED_DIR = data_path("pinoyrice_processed")
PINOYRICE_PDFS_DIR = data_path("pinoyrice_pdfs")
PINOYRICE_TXT_DIR = data_path("pinoyrice_txt")
OUTPUT_JSONL = data_path("pinoyrice_processed", "pinoyrice_corpus.jsonl")
# Batch scrape staging (raw records) when PINOYRICE_STREAM_PROCESS=false
PINOYRICE_SCRAPE_JSONL = data_path("pinoyrice_processed", "pinoyrice_scrape.jsonl")

SOURCE_NAME = "pinoyrice"
MIN_CHUNK_CHARS = int(os.getenv("PINOYRICE_MIN_CHUNK_CHARS", "100"))
MAX_CHUNK_CHARS = int(os.getenv("PINOYRICE_MAX_CHUNK_CHARS", "0"))

_UNWANTED_ENV = os.getenv(
    "PINOYRICE_UNWANTED_TEXTS",
    "HOME,RICE PRODUCTION,RICE VARIETIES,DOWNLOADS,SEED GROWERS,OFFLINE,Search for:,Menu -HOME,Are you satisfied with PINOYRICE KNOWLEDGE BANK?,uQuoted.com",
)
PINOYRICE_UNWANTED_SUBSTRINGS = [s.strip() for s in _UNWANTED_ENV.split(",") if s.strip()]
PINOYRICE_FOOTER_MARKERS = [
    "CONTACT US", "PHILRICE TEXT CENTER", "DEPARTMENT OF AGRICULTURE",
    "Are you satisfied with PINOYRICE KNOWLEDGE BANK?",
]
PINOYRICE_NOISE_LINE_PATTERNS = [
    re.compile(r"^\s*Leave a Reply\s*$", re.I),
    re.compile(r"^\s*\d*\s*Reply\s*$", re.I),
    re.compile(r"^\s*\d+\s*(year|month|day)s?\s+ago\s*$", re.I),
    re.compile(r"^\s*\d+\s*(year|month|day)\s+ago\s*$", re.I),
    re.compile(r"^\s*«\s*Previous\s*", re.I),
    re.compile(r"^\s*Next\s*»", re.I),
    re.compile(r"^\s*\d+\s*\.\.\.\s*\d+", re.I),
    re.compile(r"^\s*Subscribe\s*$", re.I),
    re.compile(r"^\s*(Guest|Author|admin|Editor)\s*$", re.I),
    re.compile(r"^\s*Posted\s+on\s+", re.I),
    re.compile(r"^\s*Published\s+", re.I),
    re.compile(r"^\s*Share\s*(this|on)\s*", re.I),
]
PINOYRICE_NOISE_LINE_SUBSTRINGS = [
    "leave a reply", "0 reply", "1 reply", "2 reply", "replies",
    "years ago", "months ago", "days ago", "« previous", "next »", "subscribe", "post comment",
]


def stream_process_enabled() -> bool:
    return os.getenv("PINOYRICE_STREAM_PROCESS", "true").strip().lower() in ("true", "1", "yes")


def delete_pdf_after_process() -> bool:
    raw = os.getenv("PINOYRICE_DELETE_PDF_AFTER_CLEAN", "").strip().lower()
    if raw in ("false", "0", "no"):
        return False
    if raw in ("true", "1", "yes"):
        return True
    return stream_process_enabled()


def scrape_jsonl_path() -> str:
    return OUTPUT_JSONL if stream_process_enabled() else PINOYRICE_SCRAPE_JSONL


def open_corpus_for_stream(*, fresh: bool | None = None) -> tuple[TextIO, str]:
    """Open pinoyrice_corpus.jsonl for append (stream) or truncate (fresh run)."""
    os.makedirs(PINOYRICE_PROCESSED_DIR, exist_ok=True)
    if fresh is None:
        fresh = os.getenv("PINOYRICE_FRESH_CORPUS", "false").strip().lower() in ("true", "1", "yes")
    path = OUTPUT_JSONL
    if fresh or not os.path.isfile(path) or os.path.getsize(path) == 0:
        mode = "w"
        console.print(f"[dim]Corpus output (new): {path}[/dim]")
    else:
        mode = "a"
        console.print(f"[dim]Corpus output (append): {path}[/dim]")
    return open(path, mode, encoding="utf-8", newline="\n"), path


def pdf_path_for_url(pdf_url: str, index: int) -> str:
    try:
        parsed = urllib.parse.urlparse(pdf_url)
        name = (parsed.path or "").split("/")[-1] or f"pinoyrice_{index}"
    except Exception:
        name = f"pinoyrice_{index}"
    name = re.sub(r"[^\w\-.]", "_", name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return os.path.join(PINOYRICE_PDFS_DIR, name[:180])


def _is_noise_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    lower = s.lower()
    if any(sub in lower for sub in PINOYRICE_NOISE_LINE_SUBSTRINGS):
        return True
    for pat in PINOYRICE_NOISE_LINE_PATTERNS:
        if pat.search(s):
            return True
    return False


def clean_pinoyrice_text(url: str, text: str) -> str:
    if not text:
        return ""
    lines = [ln.strip() for ln in text.splitlines()]
    cleaned_lines: list[str] = []
    for ln in lines:
        if not ln:
            continue
        upper_ln = ln.upper()
        if any(marker.upper() in upper_ln for marker in PINOYRICE_FOOTER_MARKERS):
            break
        if any(sub.upper() in upper_ln for sub in PINOYRICE_UNWANTED_SUBSTRINGS):
            continue
        if _is_noise_line(ln):
            continue
        alpha_count = sum(c.isalpha() for c in ln)
        if len(ln) <= 80 and alpha_count >= 5 and ln == upper_ln:
            continue
        cleaned_lines.append(ln)
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(cleaned_lines)).strip()
    if len(cleaned) < MIN_CHUNK_CHARS:
        return ""
    return cleaned


def record_to_chunks(record: dict) -> list[dict]:
    raw_text = (record.get("text") or "").strip()
    text = clean_pinoyrice_text(record.get("url") or "", raw_text)
    if not text:
        return []
    base_id = record.get("doc_id") or safe_id_from_url(record.get("url") or "", fallback="pinoyrice")
    base_id = re.sub(r"[^\w\-.]", "_", base_id)[:120] or "pinoyrice"
    chunks = chunk_text(text, MAX_CHUNK_CHARS) if MAX_CHUNK_CHARS and MAX_CHUNK_CHARS > 0 else [text]
    out: list[dict] = []
    for idx, ch in enumerate(chunks):
        if len(ch) < MIN_CHUNK_CHARS:
            continue
        doc_id = base_id if len(chunks) == 1 else f"{base_id}_chunk_{idx}"
        out.append(
            make_cpt_record(
                ch,
                SOURCE_NAME,
                doc_id,
                url=record.get("url"),
                title=record.get("title"),
            )
        )
    return out


def ingest_record_to_corpus(record: dict, corpus_f: TextIO) -> int:
    """Clean one scraped page record and append CPT chunks."""
    chunks = record_to_chunks(record)
    for ch in chunks:
        corpus_f.write(dumps_jsonl_record(ch) + "\n")
    corpus_f.flush()
    n = len(chunks)
    if n:
        console.print(f"[green]  +{n} text corpus record(s)[/green]")
    return n


def process_one_pdf(pdf_path: str) -> list[dict]:
    pages = extract_text_from_pdf(pdf_path)
    if not pages:
        return []
    noise = detect_noise_lines(pages)
    records = []
    base_id = Path(pdf_path).stem
    base_id = re.sub(r"[^\w\-.]", "_", base_id)[:120] or "pinoyrice_pdf"
    fname = os.path.basename(pdf_path)
    title = re.sub(r"[_\-]+", " ", base_id).strip() or base_id
    for item in pages:
        text = clean_pdf_text(item["text"], noise)
        if len(text) < MIN_CHUNK_CHARS:
            continue
        page_num = item["page"]
        if not MAX_CHUNK_CHARS:
            records.append(
                make_cpt_record(
                    text, SOURCE_NAME, f"{base_id}_page_{page_num}",
                    title=title, filename=fname, page=page_num,
                )
            )
        else:
            for j, ch in enumerate(chunk_text(text, MAX_CHUNK_CHARS)):
                if len(ch) >= MIN_CHUNK_CHARS:
                    records.append(
                        make_cpt_record(
                            ch, SOURCE_NAME, f"{base_id}_page_{page_num}_chunk_{j}",
                            title=title, filename=fname, page=page_num,
                        )
                    )
    return records


def ingest_pdf_to_corpus(
    pdf_path: str,
    corpus_f: TextIO,
    *,
    delete_after: bool | None = None,
) -> int:
    path_str = str(pdf_path)
    console.print(f"[dim]  Processing PDF: {os.path.basename(path_str)}[/dim]")
    records = process_one_pdf(path_str)
    for record in records:
        corpus_f.write(dumps_jsonl_record(record) + "\n")
    corpus_f.flush()
    n = len(records)
    if n:
        console.print(f"[green]  +{n} PDF corpus record(s)[/green]")
    should_delete = delete_pdf_after_process() if delete_after is None else delete_after
    if should_delete and os.path.isfile(path_str):
        try:
            os.remove(path_str)
            console.print(f"[dim]  Deleted PDF: {os.path.basename(path_str)}[/dim]")
        except OSError as exc:
            console.print(f"[yellow]  Could not delete {os.path.basename(path_str)}: {exc}[/yellow]")
    return n


def run_text_from_scrape(*, delete_staging: bool = True) -> int:
    """Batch: convert raw scrape JSONL -> CPT in pinoyrice_corpus.jsonl."""
    input_path = PINOYRICE_SCRAPE_JSONL
    if not os.path.isfile(input_path):
        console.print("[dim]No scrape staging JSONL; skip text processing.[/dim]")
        return 0
    seen_urls: set[str] = set()
    total_out = 0
    with open(input_path, "r", encoding="utf-8") as f_in, open(
        OUTPUT_JSONL, "w", encoding="utf-8", newline="\n"
    ) as f_out:
        for line in f_in:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            url = (raw.get("url") or "").strip()
            if url and url in seen_urls:
                continue
            if url:
                seen_urls.add(url)
            chunks = record_to_chunks(raw)
            if not chunks:
                continue
            for ch in chunks:
                f_out.write(dumps_jsonl_record(ch) + "\n")
            total_out += len(chunks)
    if delete_staging and os.path.isfile(input_path):
        try:
            os.remove(input_path)
        except OSError:
            pass
    return total_out


def run_pdfs(*, append: bool = True, delete_files: bool | None = None) -> int:
    if not HAS_PYMUPDF:
        return 0
    if not os.path.isdir(PINOYRICE_PDFS_DIR):
        return 0
    pdf_files = sorted(Path(PINOYRICE_PDFS_DIR).glob("*.pdf"))
    if not pdf_files:
        return 0
    use_append = append and os.path.isfile(OUTPUT_JSONL) and os.path.getsize(OUTPUT_JSONL) > 0
    mode = "a" if use_append else "w"
    console.print(f"[cyan]PDF:[/cyan] {len(pdf_files)} files -> {OUTPUT_JSONL}")
    total = 0
    with open(OUTPUT_JSONL, mode, encoding="utf-8", newline="\n") as corpus_f:
        for pdf_path in pdf_files:
            total += ingest_pdf_to_corpus(str(pdf_path), corpus_f, delete_after=delete_files)
    return total


def run_leftovers() -> None:
    """Process leftover staging JSONL, .txt debug files, or PDFs after stream scrape."""
    staging = os.path.isfile(PINOYRICE_SCRAPE_JSONL)
    pdf_files = sorted(Path(PINOYRICE_PDFS_DIR).glob("*.pdf")) if os.path.isdir(PINOYRICE_PDFS_DIR) else []
    txt_files = sorted(Path(PINOYRICE_TXT_DIR).glob("*.txt")) if os.path.isdir(PINOYRICE_TXT_DIR) else []
    if not staging and not pdf_files and not txt_files:
        console.print("[dim]Stream mode: no leftover PinoyRice files.[/dim]")
        return
    console.rule("[bold cyan]PinoyRice leftovers (stream cleanup)[/bold cyan]")
    text_out = run_text_from_scrape(delete_staging=True) if staging else 0
    if txt_files:
        for path in txt_files:
            try:
                path.unlink()
            except OSError:
                pass
        console.print(f"[dim]Removed {len(txt_files)} leftover .txt file(s).[/dim]")
    pdf_out = run_pdfs(append=True, delete_files=True) if pdf_files else 0
    console.print(f"Leftover text: [green]{text_out}[/green], PDF: [green]{pdf_out}[/green]")


def run(*, leftovers_only: bool | None = None):
    if leftovers_only is None:
        leftovers_only = stream_process_enabled()
    if leftovers_only:
        run_leftovers()
        return
    console.rule("[bold cyan]PinoyRice processing (text + PDF)[/bold cyan]")
    if delete_pdf_after_process():
        console.print("[dim]PDFs will be deleted after CPT.[/dim]")
    text_out = run_text_from_scrape()
    pdf_out = run_pdfs(
        append=os.path.isfile(OUTPUT_JSONL) and os.path.getsize(OUTPUT_JSONL) > 0,
        delete_files=delete_pdf_after_process(),
    )
    console.rule("[bold green]Done[/bold green]")
    console.print(f"Text CPT records: [green]{text_out}[/green]")
    console.print(f"PDF CPT records: [green]{pdf_out}[/green]")
    console.print(f"Corpus: [cyan]{OUTPUT_JSONL}[/cyan]")
