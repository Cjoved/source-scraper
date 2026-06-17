"""
IRRI text + PDF -> CPT JSONL.
Input: data/irri_processed/text/*.txt, data/irri_pdfs/*.pdf
Output: data/irri_processed/irri_corpus.jsonl
"""
import os
import re
import hashlib
import sys
import urllib.parse
from pathlib import Path
from typing import TextIO

from rich.console import Console
from dotenv import load_dotenv

from src.openstat.config import data_path
from src.openstat.agri_corpus.txt_cpt import text_to_cpt_records
from src.openstat.agri_corpus.cpt_utils import make_cpt_record
from src.openstat.agri_corpus.pdf_utils import (
    HAS_PDFPLUMBER,
    HAS_PYMUPDF,
    clean_pdf_text,
    detect_noise_lines,
    extract_text_from_pdf,
)
from src.openstat.agri_corpus.text_utils import chunk_text
from src.utils.jsonl import dumps_jsonl_record

load_dotenv()
console = Console()

IRRI_TEXT_DIR = data_path("irri_processed", "text")
IRRI_PDFS_DIR = data_path("irri_pdfs")
IRRI_PROCESSED_DIR = data_path("irri_processed")
OUTPUT_JSONL = data_path("irri_processed", "irri_corpus.jsonl")

SOURCE_NAME = "irri"
MIN_CHUNK_CHARS = int(os.getenv("IRRI_MIN_CHUNK_CHARS", "100"))
MAX_CHUNK_CHARS = int(os.getenv("IRRI_MAX_CHUNK_CHARS", "0"))
CHUNK_BY_PAGE = True


def stream_process_enabled() -> bool:
    return os.getenv("IRRI_STREAM_PROCESS", "true").strip().lower() in ("true", "1", "yes")


def delete_txt_after_process() -> bool:
    raw = os.getenv("IRRI_DELETE_TXT_AFTER_PROCESS", "").strip().lower()
    if raw in ("false", "0", "no"):
        return False
    if raw in ("true", "1", "yes"):
        return True
    return stream_process_enabled()


def delete_pdf_after_process() -> bool:
    raw = os.getenv("IRRI_DELETE_PDF_AFTER_CLEAN", "").strip().lower()
    if raw in ("false", "0", "no"):
        return False
    if raw in ("true", "1", "yes"):
        return True
    return stream_process_enabled()

# Suffix na tinatanggal sa title (para malinis na doc_id at text)
IRRI_TITLE_SUFFIX = re.compile(
    r"\s*[_\|]\s*International Rice Research Institute\s*$",
    re.IGNORECASE,
)
# Footer noise: "For more information, please contact:" hanggang dulo
FOOTER_START = re.compile(
    r"\n\s*For more information, please contact\s*:?\s*\n",
    re.IGNORECASE,
)
# Leading noise: standalone SHARE, o linya na date lang (e.g. " May 30, 2018")
DATE_LINE = re.compile(
    r"^\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\d{4}\s*$",
    re.IGNORECASE,
)


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _safe_log_name(name: str) -> str:
    return name.encode("ascii", errors="replace").decode("ascii")


def _parse_txt_content(raw: str) -> tuple[str, str, str]:
    """Kunin URL, Title, at body mula sa .txt. Body lang ang ibabalik na 'content' for CPT; URL/Title metadata."""
    raw = raw.strip()
    url = ""
    title = ""
    body = raw
    if raw.startswith("URL:"):
        lines = raw.split("\n")
        if len(lines) >= 1:
            url = lines[0].replace("URL:", "").strip()
        if len(lines) >= 2 and lines[1].strip().lower().startswith("title:"):
            title = lines[1].replace("Title:", "").strip()
        body_start = 2
        if len(lines) >= 3 and lines[2].strip().lower().startswith("date:"):
            body_start = 3
        if len(lines) > body_start:
            body = "\n".join(lines[body_start:]).strip()
    return url, title, body


def _clean_title_for_id(title: str) -> str:
    """Tanggalin ' | International Rice Research Institute' at iba pang noise; for doc_id."""
    if not title:
        return "irri_unknown"
    t = IRRI_TITLE_SUFFIX.sub("", title).strip()
    t = re.sub(r"\s+", " ", t)
    return t or "irri_unknown"


def _safe_doc_id(clean_title: str, max_len: int = 100) -> str:
    """Slug from cleaned title: lowercase, spaces -> single underscore, alphanumeric + underscore."""
    s = clean_title.lower().strip()
    s = re.sub(r"[^\w\s\-]", " ", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return (s[:max_len] if max_len else s) or "irri_unknown"


def _url_slug_for_id(url: str, max_len: int = 56) -> str:
    """Extract stable URL slug suffix to disambiguate same-title IRRI articles."""
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
        core = slug[:max_len]
        return f"{core}_{digest}"
    except Exception:
        return ""


def _clean_body(body: str, clean_title: str = "") -> str:
    """
    Linisin body: tanggalin duplicate title line, date + SHARE, footer (For more information...),
    at normalize whitespace. Output = cleaned text lang (walang noise) para sa CPT.
    """
    if not body:
        return ""
    if FOOTER_START.search(body):
        body = FOOTER_START.split(body)[0].strip()
    lines = body.split("\n")
    out = []
    skip_leading = True
    for ln in lines:
        s = ln.strip()
        if skip_leading:
            if not s:
                continue
            if s.upper() == "SHARE" or DATE_LINE.match(s):
                continue
            if clean_title and s == clean_title:
                continue
            skip_leading = False
        out.append(ln)
    body = "\n".join(out).strip()
    lines = [ln.strip() for ln in body.split("\n")]
    out = []
    prev_blank = False
    for ln in lines:
        is_blank = not ln
        if is_blank and prev_blank:
            continue
        prev_blank = is_blank
        out.append(ln)
    return "\n".join(out).strip()


def _clean_irri_text(raw: str) -> tuple[str, str, str]:
    """Parse at linisin: return (url, clean_title, cleaned_body)."""
    url, title, body = _parse_txt_content(raw)
    clean_title = _clean_title_for_id(title)
    cleaned_body = _clean_body(body, clean_title=clean_title)
    return url, clean_title, cleaned_body


def _pdf_title_from_stem(stem: str) -> str:
    title = re.sub(r"[_\-]+", " ", stem).strip()
    return title or stem


def _safe_pdf_base_id(stem: str) -> str:
    return re.sub(r"[^\w\-.]", "_", stem)[:120] or "irri_pdf"


def txt_to_cpt_records(txt_path: str) -> list[dict]:
    """Read .txt -> parse -> clean -> CPT records."""
    path = Path(txt_path)
    if not path.is_file() or path.suffix.lower() != ".txt":
        return []
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except Exception as e:
        console.print(f"[yellow]Read failed {path.name}: {e}[/yellow]")
        return []
    if not raw:
        return []
    url, clean_title, text = _clean_irri_text(raw)
    if not text or len(text) < MIN_CHUNK_CHARS:
        return []
    base_id = _safe_doc_id(clean_title, max_len=100)
    url_slug = _url_slug_for_id(url, max_len=48)
    if url_slug and not base_id.endswith(url_slug):
        base_id = f"{base_id}_{url_slug}"
    return text_to_cpt_records(
        text,
        source=SOURCE_NAME,
        base_id=base_id,
        min_chars=MIN_CHUNK_CHARS,
        max_chars=MAX_CHUNK_CHARS,
        filename=path.name,
        url=url or None,
        title=clean_title or None,
    )


def process_one_pdf(pdf_path: str) -> list[dict]:
    pages = extract_text_from_pdf(pdf_path)
    if not pages:
        return []
    noise_lines = detect_noise_lines(pages)
    records: list[dict] = []
    stem = Path(pdf_path).stem
    base_id = _safe_pdf_base_id(stem)
    fname = os.path.basename(pdf_path)
    title = _pdf_title_from_stem(stem)
    for item in pages:
        page_num = item["page"]
        text = clean_pdf_text(item["text"], noise_lines)
        if len(text) < MIN_CHUNK_CHARS:
            continue
        if CHUNK_BY_PAGE and not MAX_CHUNK_CHARS:
            records.append(
                make_cpt_record(
                    text,
                    SOURCE_NAME,
                    f"{base_id}_page_{page_num}",
                    title=title,
                    filename=fname,
                    page=page_num,
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
                        SOURCE_NAME,
                        f"{base_id}_page_{page_num}_chunk_{j}",
                        title=title,
                        filename=fname,
                        page=page_num,
                    )
                )
    return records


def pdf_path_for_url(pdf_url: str) -> str:
    from src.openstat.agri_corpus.scraper_utils import safe_filename_from_url

    fname = safe_filename_from_url(pdf_url, max_len=160, suffix=".pdf")
    return os.path.join(IRRI_PDFS_DIR, fname)


def open_corpus_for_stream(*, fresh: bool | None = None) -> tuple[TextIO, str]:
    """Open irri_corpus.jsonl for append (stream) or truncate (fresh run)."""
    os.makedirs(IRRI_PROCESSED_DIR, exist_ok=True)
    if fresh is None:
        fresh = os.getenv("IRRI_FRESH_CORPUS", "false").strip().lower() in ("true", "1", "yes")
    if fresh or not os.path.isfile(OUTPUT_JSONL) or os.path.getsize(OUTPUT_JSONL) == 0:
        mode = "w"
        console.print(f"[dim]Corpus output (new): {OUTPUT_JSONL}[/dim]")
    else:
        mode = "a"
        console.print(f"[dim]Corpus output (append): {OUTPUT_JSONL}[/dim]")
    return open(OUTPUT_JSONL, mode, encoding="utf-8", newline="\n"), OUTPUT_JSONL


def ingest_txt_to_corpus(
    txt_path: str,
    corpus_f: TextIO,
    *,
    delete_after: bool | None = None,
) -> int:
    """Parse one .txt, append CPT records, optionally delete the file."""
    path_str = str(txt_path)
    records = txt_to_cpt_records(path_str)
    for record in records:
        corpus_f.write(dumps_jsonl_record(record) + "\n")
    corpus_f.flush()
    n = len(records)
    if n:
        console.print(f"[green]  +{n} text corpus record(s)[/green]")
    should_delete = delete_txt_after_process() if delete_after is None else delete_after
    if should_delete and os.path.isfile(path_str):
        try:
            os.remove(path_str)
            console.print(f"[dim]  Deleted .txt: {os.path.basename(path_str)}[/dim]")
        except OSError as exc:
            console.print(f"[yellow]  Could not delete {os.path.basename(path_str)}: {exc}[/yellow]")
    return n


def ingest_pdf_to_corpus(
    pdf_path: str,
    corpus_f: TextIO,
    *,
    delete_after: bool | None = None,
) -> int:
    """Extract one PDF, append CPT records, optionally delete the file."""
    path_str = str(pdf_path)
    console.print(f"[dim]  Processing PDF: {os.path.basename(path_str)}[/dim]")
    records = process_one_pdf(path_str)
    for record in records:
        corpus_f.write(dumps_jsonl_record(record) + "\n")
    corpus_f.flush()
    n = len(records)
    if n:
        console.print(f"[green]  +{n} PDF corpus record(s)[/green]")
    else:
        console.print("[yellow]  No text extracted from PDF (skipped).[/yellow]")
    should_delete = delete_pdf_after_process() if delete_after is None else delete_after
    if should_delete and os.path.isfile(path_str):
        try:
            os.remove(path_str)
            console.print(f"[dim]  Deleted PDF: {os.path.basename(path_str)}[/dim]")
        except OSError as exc:
            console.print(f"[yellow]  Could not delete {os.path.basename(path_str)}: {exc}[/yellow]")
    return n


def run_text(*, append: bool = False, delete_files: bool | None = None) -> int:
    if not os.path.isdir(IRRI_TEXT_DIR):
        console.print(f"[yellow]Folder not found: {IRRI_TEXT_DIR}[/yellow]")
        console.print("[dim]Run IRRI scraper first (IRRI=true then python main.py).[/dim]")
        return 0
    txt_files = sorted(Path(IRRI_TEXT_DIR).glob("*.txt"))
    if not txt_files:
        console.print(f"[yellow]No .txt files in {IRRI_TEXT_DIR}[/yellow]")
        return 0
    console.print(f"[cyan]Text:[/cyan] {len(txt_files)} .txt files -> {OUTPUT_JSONL}")
    total = 0
    mode = "a" if append and os.path.isfile(OUTPUT_JSONL) and os.path.getsize(OUTPUT_JSONL) > 0 else "w"
    with open(OUTPUT_JSONL, mode, encoding="utf-8", newline="\n") as corpus_f:
        for i, txt_path in enumerate(txt_files):
            n = ingest_txt_to_corpus(str(txt_path), corpus_f, delete_after=delete_files)
            if not n:
                continue
            if (i + 1) % 50 == 0 or i == 0 or i + 1 == len(txt_files):
                console.print(
                    f"[dim]({i + 1}/{len(txt_files)}) {_safe_log_name(txt_path.name)} -> {n} chunk(s)[/dim]"
                )
            total += n
    return total


def run_pdfs(*, append: bool = True, delete_files: bool | None = None) -> int:
    if not HAS_PYMUPDF:
        console.print("[yellow]PyMuPDF not installed; skip IRRI PDF processing.[/yellow]")
        return 0
    if HAS_PDFPLUMBER:
        console.print("[dim]Table extraction enabled (pdfplumber).[/dim]")
    if not os.path.isdir(IRRI_PDFS_DIR):
        console.print(f"[dim]No PDF folder: {IRRI_PDFS_DIR}[/dim]")
        return 0
    pdf_files = sorted(Path(IRRI_PDFS_DIR).glob("*.pdf"))
    if not pdf_files:
        console.print(f"[dim]No PDFs in {IRRI_PDFS_DIR}[/dim]")
        return 0
    use_append = append and os.path.isfile(OUTPUT_JSONL) and os.path.getsize(OUTPUT_JSONL) > 0
    mode = "a" if use_append else "w"
    console.print(f"[cyan]PDF:[/cyan] {len(pdf_files)} files -> {OUTPUT_JSONL} ({'append' if use_append else 'write'})")
    total = 0
    with open(OUTPUT_JSONL, mode, encoding="utf-8", newline="\n") as corpus_f:
        for i, pdf_path in enumerate(pdf_files):
            n = ingest_pdf_to_corpus(str(pdf_path), corpus_f, delete_after=delete_files)
            if not n:
                continue
            if (i + 1) % 10 == 0 or i == 0 or i + 1 == len(pdf_files):
                console.print(
                    f"[dim]({i + 1}/{len(pdf_files)}) {_safe_log_name(pdf_path.name)} -> {n} chunk(s)[/dim]"
                )
            total += n
    return total


def run_leftovers() -> None:
    """Process any .txt / .pdf left on disk after stream scrape."""
    txt_files = sorted(Path(IRRI_TEXT_DIR).glob("*.txt")) if os.path.isdir(IRRI_TEXT_DIR) else []
    pdf_files = sorted(Path(IRRI_PDFS_DIR).glob("*.pdf")) if os.path.isdir(IRRI_PDFS_DIR) else []
    if not txt_files and not pdf_files:
        console.print("[dim]Stream mode: no leftover IRRI files.[/dim]")
        return
    console.rule("[bold cyan]IRRI leftovers (stream cleanup)[/bold cyan]")
    txt_total = run_text(append=True, delete_files=True) if txt_files else 0
    pdf_total = run_pdfs(append=True, delete_files=True) if pdf_files else 0
    console.print(f"Leftover text: [green]{txt_total}[/green], PDF: [green]{pdf_total}[/green]")


def run(*, leftovers_only: bool | None = None):
    _configure_console_encoding()
    os.makedirs(IRRI_PROCESSED_DIR, exist_ok=True)
    if leftovers_only is None:
        leftovers_only = stream_process_enabled()
    if leftovers_only:
        run_leftovers()
        return
    console.rule("[bold cyan]IRRI processing (text + PDF)[/bold cyan]")
    if delete_txt_after_process() or delete_pdf_after_process():
        console.print("[dim]Files will be deleted after CPT.[/dim]")
    txt_total = run_text(delete_files=delete_txt_after_process())
    pdf_total = run_pdfs(
        append=os.path.isfile(OUTPUT_JSONL) and os.path.getsize(OUTPUT_JSONL) > 0,
        delete_files=delete_pdf_after_process(),
    )
    console.rule("[bold green]Done[/bold green]")
    console.print(f"Text CPT records: [green]{txt_total}[/green]")
    console.print(f"PDF CPT records: [green]{pdf_total}[/green]")
    console.print(f"Corpus: [cyan]{os.path.abspath(OUTPUT_JSONL)}[/cyan]")


if __name__ == "__main__":
    run()
