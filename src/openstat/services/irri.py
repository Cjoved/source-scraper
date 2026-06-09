"""
IRRI .txt → CPT JSON. Input: data/irri_processed/text/*.txt → data/irri_processed/irri_corpus.jsonl.
May cleaning muna: tanggalin noise (URL/Title header, SHARE, footer contact) bago CPT.
"""
import os
import re
import json
from pathlib import Path

from rich.console import Console
from dotenv import load_dotenv

from src.openstat.config import data_path
from src.openstat.agri_corpus.txt_cpt import text_to_cpt_records
from src.utils.jsonl import dumps_jsonl_record

load_dotenv()
console = Console()

IRRI_TEXT_DIR = data_path("irri_processed", "text")
IRRI_PROCESSED_DIR = data_path("irri_processed")
IRRI_PER_FILE_DIR = data_path("irri_processed", "per_file")
OUTPUT_JSONL = data_path("irri_processed", "irri_corpus.jsonl")

SOURCE_NAME = "irri"
MIN_CHUNK_CHARS = int(os.getenv("IRRI_MIN_CHUNK_CHARS", "100"))
MAX_CHUNK_CHARS = int(os.getenv("IRRI_MAX_CHUNK_CHARS", "0"))

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
DATE_LINE = re.compile(r"^\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s*\d{4}\s*$", re.IGNORECASE)


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
        if len(lines) > 2:
            body = "\n".join(lines[2:]).strip()
    return url, title, body


def _clean_title_for_id(title: str) -> str:
    """Tanggalin ' | International Rice Research Institute' at iba pang noise; for doc_id."""
    if not title:
        return "irri_unknown"
    t = IRRI_TITLE_SUFFIX.sub("", title).strip()
    t = re.sub(r"\s+", " ", t)
    return t or "irri_unknown"


def _safe_doc_id(clean_title: str, max_len: int = 100) -> str:
    """Slug from cleaned title: lowercase, spaces → single underscore, alphanumeric + underscore."""
    s = clean_title.lower().strip()
    s = re.sub(r"[^\w\s\-]", " ", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return (s[:max_len] if max_len else s) or "irri_unknown"


def _clean_body(body: str, clean_title: str = "") -> str:
    """
    Linisin body: tanggalin duplicate title line, date + SHARE, footer (For more information...),
    at normalize whitespace. Output = cleaned text lang (walang noise) para sa CPT.
    """
    if not body:
        return ""
    # Tanggalin footer (For more information, please contact ...)
    if FOOTER_START.search(body):
        body = FOOTER_START.split(body)[0].strip()
    # Tanggalin leading: blank, date line, SHARE, at duplicate title (kapareho ng clean_title)
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
    # Normalize: strip each line, collapse 3+ newlines to 2
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


def txt_to_cpt_records(txt_path: str) -> list[dict]:
    """Read .txt → parse → clean → CPT records."""
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
    _url, clean_title, text = _clean_irri_text(raw)
    if not text or len(text) < MIN_CHUNK_CHARS:
        return []
    base_id = _safe_doc_id(clean_title, max_len=100)
    return text_to_cpt_records(
        text,
        source=SOURCE_NAME,
        base_id=base_id,
        min_chars=MIN_CHUNK_CHARS,
        max_chars=MAX_CHUNK_CHARS,
        filename=path.name,
    )


def run():
    if not os.path.isdir(IRRI_TEXT_DIR):
        console.print(f"[yellow]Folder not found: {IRRI_TEXT_DIR}[/yellow]")
        console.print("[dim]Run IRRI scraper first (IRRI=true then python main.py).[/dim]")
        return
    os.makedirs(IRRI_PER_FILE_DIR, exist_ok=True)
    txt_files = sorted(Path(IRRI_TEXT_DIR).glob("*.txt"))
    if not txt_files:
        console.print(f"[yellow]No .txt files in {IRRI_TEXT_DIR}[/yellow]")
        return
    console.rule("[bold cyan]IRRI .txt → CPT JSON[/bold cyan]")
    console.print(f"Processing {len(txt_files)} .txt files → {IRRI_PROCESSED_DIR}")
    total = 0
    with open(OUTPUT_JSONL, "w", encoding="utf-8", newline="\n") as corpus_f:
        for i, txt_path in enumerate(txt_files):
            records = txt_to_cpt_records(str(txt_path))
            if not records:
                continue
            console.print(f"[dim]({i + 1}/{len(txt_files)}) {txt_path.name} → {len(records)} chunk(s)[/dim]")
            # Per-file JSON filename: same style as PhilRice News (safe stem of .txt)
            safe_stem = re.sub(r"[^\w\-.]", "_", txt_path.stem)[:180] or "irri_unknown"
            per_file_path = Path(IRRI_PER_FILE_DIR) / f"{safe_stem}.json"
            with open(per_file_path, "w", encoding="utf-8") as jf:
                json.dump(records, jf, ensure_ascii=False, indent=2)
            for r in records:
                corpus_f.write(dumps_jsonl_record(r) + "\n")
            total += len(records)
    console.rule("[bold green]Done[/bold green]")
    console.print(f"Total CPT records: [green]{total}[/green]")
    console.print(f"Corpus: [cyan]{os.path.abspath(OUTPUT_JSONL)}[/cyan]")


if __name__ == "__main__":
    run()
