"""PinoyRice processing: text corpus + PDFs → CPT. All I/O under data/pinoyrice_* and data/pinoyrice_pdfs."""
import os
import re
import json
from pathlib import Path

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
PINOYRICE_INPUT_JSONL = data_path("pinoyrice_processed", "pinoyrice_corpus.jsonl")
PINOYRICE_PER_FILE_CPT_DIR = data_path("pinoyrice_processed", "per_file_cpt")
PINOYRICE_OUTPUT_JSONL = data_path("pinoyrice_processed", "pinoyrice_corpus_chunked.jsonl")
PINOYRICE_PER_FILE_PDF_DIR = data_path("pinoyrice_processed", "per_file_pdf")
PINOYRICE_PDFS_JSONL = data_path("pinoyrice_processed", "pinoyrice_pdfs_corpus.jsonl")

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
        out.append(make_cpt_record(ch, SOURCE_NAME, doc_id, url=record.get("url"), title=record.get("title")))
    return out


def process_one_pdf(pdf_path: str) -> list[dict]:
    pages = extract_text_from_pdf(pdf_path)
    if not pages:
        return []
    noise = detect_noise_lines(pages)
    records = []
    base_id = Path(pdf_path).stem
    fname = os.path.basename(pdf_path)
    for item in pages:
        text = clean_pdf_text(item["text"], noise)
        if len(text) < MIN_CHUNK_CHARS:
            continue
        page_num = item["page"]
        if not MAX_CHUNK_CHARS:
            records.append(make_cpt_record(text, SOURCE_NAME, f"{base_id}_page_{page_num}", filename=fname, page=page_num))
        else:
            for j, ch in enumerate(chunk_text(text, MAX_CHUNK_CHARS)):
                if len(ch) >= MIN_CHUNK_CHARS:
                    records.append(make_cpt_record(ch, SOURCE_NAME, f"{base_id}_page_{page_num}_chunk_{j}", filename=fname, page=page_num))
    return records


def run_text():
    if not os.path.isfile(PINOYRICE_INPUT_JSONL):
        console.print("[dim]No corpus JSONL; skip text processing.[/dim]")
        return 0
    os.makedirs(PINOYRICE_PER_FILE_CPT_DIR, exist_ok=True)
    for f in Path(PINOYRICE_PER_FILE_CPT_DIR).glob("*.json"):
        try:
            f.unlink()
        except Exception:
            pass
    seen_urls: set[str] = set()
    total_out = 0
    per_url_buffers: dict[str, list[dict]] = {}
    with open(PINOYRICE_INPUT_JSONL, "r", encoding="utf-8") as f_in, open(
        PINOYRICE_OUTPUT_JSONL, "w", encoding="utf-8", newline="\n"
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
            key = safe_id_from_url(url, fallback="pinoyrice") if url else (raw.get("doc_id") or "rec")
            if key not in per_url_buffers:
                per_url_buffers[key] = []
            per_url_buffers[key].extend(chunks)
    for key, records in per_url_buffers.items():
        safe = re.sub(r"[^\w\-.]", "_", key)[:180] or "pinoyrice"
        path = Path(PINOYRICE_PER_FILE_CPT_DIR) / f"{safe}.json"
        try:
            with open(path, "w", encoding="utf-8") as jf:
                json.dump(records, jf, ensure_ascii=False, indent=2)
        except Exception as e:
            console.print(f"[yellow]Write {path.name}: {e}[/yellow]")
    return total_out


def run_pdfs():
    if not HAS_PYMUPDF:
        return 0
    if not os.path.isdir(PINOYRICE_PDFS_DIR):
        return 0
    pdf_files = sorted(Path(PINOYRICE_PDFS_DIR).glob("*.pdf"))
    if not pdf_files:
        return 0
    os.makedirs(PINOYRICE_PER_FILE_PDF_DIR, exist_ok=True)
    total = 0
    with open(PINOYRICE_PDFS_JSONL, "w", encoding="utf-8", newline="\n") as corpus_f:
        for pdf_path in pdf_files:
            records = process_one_pdf(str(pdf_path))
            safe_stem = re.sub(r"[^\w\-.]", "_", pdf_path.stem)[:180]
            per_path = Path(PINOYRICE_PER_FILE_PDF_DIR) / f"{safe_stem}.json"
            with open(per_path, "w", encoding="utf-8") as jf:
                json.dump(records, jf, ensure_ascii=False, indent=2)
            for r in records:
                corpus_f.write(dumps_jsonl_record(r) + "\n")
            total += len(records)
    return total


def run():
    console.rule("[bold cyan]PinoyRice processing (text + PDF)")
    text_out = run_text()
    pdf_out = run_pdfs()
    console.rule("[bold green]Done")
    console.print(f"Text CPT chunks: [green]{text_out}[/green]")
    console.print(f"PDF CPT chunks: [green]{pdf_out}[/green]")
    console.print(f"Outputs: [cyan]{PINOYRICE_PROCESSED_DIR}[/cyan]")
