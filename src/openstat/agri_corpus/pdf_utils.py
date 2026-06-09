"""
Shared PDF utilities: extract text + tables, detect/remove noise lines, clean text.
"""
import re
from collections import Counter

from src.utils.text_sanitize import sanitize_corpus_text

try:
    import fitz
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

NOISE_LINE_PATTERN = re.compile(r"^\s*\d{1,4}\s*$", re.MULTILINE)


def table_to_text(table: list[list]) -> str:
    """Convert table (list of rows) to readable text (pipe-separated)."""
    if not table:
        return ""
    return "\n".join(" | ".join(str(c or "").strip() for c in row) for row in table)


def extract_tables_from_page(pdf_path: str, page_num: int) -> list[str]:
    """Extract tables from one page using pdfplumber."""
    if not HAS_PDFPLUMBER:
        return []
    out = []
    try:
        with pdfplumber.open(pdf_path) as doc:
            if 1 <= page_num <= len(doc.pages):
                for t in doc.pages[page_num - 1].extract_tables() or []:
                    txt = table_to_text(t)
                    if txt.strip():
                        out.append(txt)
    except Exception:
        pass
    return out


def extract_text_from_pdf(pdf_path: str) -> list[dict]:
    """Extract text per page; append [Table] blocks if pdfplumber available."""
    if not HAS_PYMUPDF:
        return []
    out = []
    plumber_doc = None
    try:
        if HAS_PDFPLUMBER:
            try:
                plumber_doc = pdfplumber.open(pdf_path)
            except Exception:
                plumber_doc = None
        doc = fitz.open(pdf_path)
        for i in range(len(doc)):
            text = doc[i].get_text()
            if plumber_doc is not None and 1 <= i + 1 <= len(plumber_doc.pages):
                tables = []
                try:
                    for t in plumber_doc.pages[i].extract_tables() or []:
                        txt = table_to_text(t)
                        if txt.strip():
                            tables.append(txt)
                except Exception:
                    pass
                if tables:
                    text = (text.strip() if text else "") + "\n\n[Table]\n" + "\n\n[Table]\n".join(tables)
            if text and text.strip():
                out.append({"page": i + 1, "text": text.strip()})
        doc.close()
    except Exception:
        return []
    finally:
        if plumber_doc is not None:
            try:
                plumber_doc.close()
            except Exception:
                pass
    return out


def detect_noise_lines(
    pages: list[dict],
    min_freq_ratio: float = 0.3,
    max_line_len: int = 120,
) -> set[str]:
    """Detect running headers/footers by frequency across pages."""
    if not pages:
        return set()
    total = len(pages)
    cnt: Counter = Counter()
    for item in pages:
        seen = set()
        for line in item["text"].split("\n"):
            s = line.strip()
            if s and s not in seen:
                cnt[s] += 1
                seen.add(s)
    threshold = max(2, int(total * min_freq_ratio))
    return {line for line, c in cnt.items() if c >= threshold and len(line) <= max_line_len}


def clean_pdf_text(text: str, noise_lines: set[str] | None = None) -> str:
    """Normalize whitespace, remove standalone page numbers and detected noise lines."""
    if not text or not text.strip():
        return ""
    text = re.sub(r"\r\n", "\n", text)
    text = NOISE_LINE_PATTERN.sub("", text)
    if noise_lines:
        for line in noise_lines:
            text = re.sub(r"(?m)^" + re.escape(line) + r"\s*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return sanitize_corpus_text(text)
