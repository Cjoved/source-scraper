"""Pull <table> grids from Scrapling / parsel roots for CSV export."""

from __future__ import annotations

import html as html_module
import re
from typing import Any

from src.scraper.parsers.prism_browser_page import content_selectors_for_url
from src.scraper.prism_browser_config import PrismBrowserConfig


def normalize_cell_text(raw: str) -> str:
    t = html_module.unescape(raw or "")
    t = t.replace("\u00a0", " ").strip()
    return re.sub(r"\s+", " ", t).strip()


def extract_tables_from_page(page: Any, norm_url: str, cfg: PrismBrowserConfig) -> list[list[list[str]]]:
    selectors = content_selectors_for_url(norm_url, cfg)
    if not selectors:
        selectors = ["body"]

    tables_out: list[list[list[str]]] = []
    for sel in selectors:
        try:
            for table in page.css(f"{sel} table"):
                rows: list[list[str]] = []
                for tr in table.css("tr"):
                    cells: list[str] = []
                    for cell in tr.css("th, td"):
                        parts = cell.xpath(".//text()").getall()
                        cells.append(normalize_cell_text(" ".join(parts)))
                    if any(c for c in cells):
                        rows.append(cells)
                if rows:
                    tables_out.append(rows)
        except Exception:
            continue
    return tables_out
