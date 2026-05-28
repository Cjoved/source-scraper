"""
Shared utilities for PhilRice/PinoyRice scrapers and CPT processing.
"""
from .text_utils import chunk_text, safe_id_from_url
from .pdf_utils import (
    extract_text_from_pdf,
    extract_tables_from_page,
    detect_noise_lines,
    clean_pdf_text,
    HAS_PYMUPDF,
    HAS_PDFPLUMBER,
)
from .cpt_utils import make_cpt_record

__all__ = [
    "chunk_text",
    "safe_id_from_url",
    "extract_text_from_pdf",
    "extract_tables_from_page",
    "detect_noise_lines",
    "clean_pdf_text",
    "HAS_PYMUPDF",
    "HAS_PDFPLUMBER",
    "make_cpt_record",
]
