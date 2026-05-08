"""Append extracted HTML tables as uniform CSV rows."""

from __future__ import annotations

import csv
from pathlib import Path


def append_browser_tables_csv(
    path: Path,
    *,
    source_url: str,
    page_title: str,
    scraped_at: str,
    tables: list[list[list[str]]],
    max_cols: int,
) -> int:
    """Write one row per table cell row; returns rows written."""
    if not tables or max_cols < 1:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = path.is_file() and path.stat().st_size > 0
    headers = (
        ["source_url", "page_title", "scraped_at", "table_index", "row_index"]
        + [f"col_{i}" for i in range(max_cols)]
    )

    rows_written = 0
    mode = "a" if file_exists else "w"
    with path.open(mode, newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for ti, table in enumerate(tables):
            for ri, row in enumerate(table):
                rec: dict[str, str | int] = {
                    "source_url": source_url,
                    "page_title": page_title,
                    "scraped_at": scraped_at,
                    "table_index": ti,
                    "row_index": ri,
                }
                for i in range(max_cols):
                    rec[f"col_{i}"] = row[i] if i < len(row) else ""
                writer.writerow(rec)
                rows_written += 1
    return rows_written
