"""OpenSTAT tabular data → CPT sentence records.

Converts long-format PSA farmgate price tables (one row per geo/commodity/month)
into natural-language CPT JSONL suitable for continued pre-training.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console

from src.services.config import data_path
from src.utils.cpt import make_cpt_record

console = Console()

SOURCE_NAME = "openstat"
OPENSTAT_PROCESSED_DIR = data_path("openstat_processed")
OPENSTAT_TABLE_CSV = OPENSTAT_PROCESSED_DIR / "openstat_table.csv"
OPENSTAT_OUTPUT_JSONL = OPENSTAT_PROCESSED_DIR / "openstat_corpus.jsonl"

_ANNUAL_MONTHS = {"annual", "yearly", "year", "total"}
_DOC_ID_SAFE = re.compile(r"[^a-zA-Z0-9_-]+")


def _safe_token(value: Any, fallback: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    if not text or text == "nan":
        return fallback
    cleaned = _DOC_ID_SAFE.sub("_", text).strip("_")
    return cleaned[:80] or fallback


def row_to_sentence(row: pd.Series) -> str:
    """Build one farmgate-price sentence from a long-format OpenSTAT row."""
    month = str(row.get("Month") or "").strip()
    year = row.get("Year")
    geolocation = str(row.get("Geolocation") or "").strip()
    commodity = str(row.get("Commodity") or row.get("Commodity Type") or "commodity").strip()
    price = row.get("Price")

    year_text = str(int(year)) if pd.notna(year) else "an unknown year"
    month_text = month or "an unknown month"
    location_text = geolocation or "an unknown location"

    if pd.isna(price):
        return (
            f"In {month_text} {year_text}, the farmgate price of {commodity} "
            f"in {location_text} had no recorded data."
        )

    price_value = float(price)
    return (
        f"In {month_text} {year_text}, the farmgate price of {commodity} "
        f"in {location_text} was ₱{price_value:.2f} per kilogram."
    )


def _make_doc_id(row: pd.Series, index: int) -> str:
    return "_".join(
        [
            "openstat",
            _safe_token(row.get("Geolocation"), "geo"),
            _safe_token(row.get("Commodity") or row.get("Commodity Type"), "commodity"),
            _safe_token(row.get("Year"), "year"),
            _safe_token(row.get("Month"), "month"),
            str(index),
        ]
    )


def _prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    work = df.copy()
    if "Month" in work.columns:
        month_mask = work["Month"].astype(str).str.strip().str.lower()
        work = work[~month_mask.isin(_ANNUAL_MONTHS)]

    required = {"Geolocation", "Year", "Month"}
    missing = required - set(work.columns)
    if missing:
        raise ValueError(f"OpenSTAT table missing required columns: {sorted(missing)}")

    return work.reset_index(drop=True)


def tabular_to_cpt_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a cleaned long-format OpenSTAT DataFrame to CPT records."""
    prepared = _prepare_dataframe(df)
    records: list[dict[str, Any]] = []

    for idx, row in prepared.iterrows():
        text = row_to_sentence(row)
        doc_id = _make_doc_id(row, int(idx))
        rec = make_cpt_record(text, SOURCE_NAME, doc_id)
        rec.update(
            {
                "geolocation": str(row.get("Geolocation") or "").strip(),
                "commodity": str(row.get("Commodity") or row.get("Commodity Type") or "").strip(),
                "commodity_type": str(row.get("Commodity Type") or "").strip(),
                "year": int(row["Year"]) if pd.notna(row.get("Year")) else None,
                "month": str(row.get("Month") or "").strip(),
            }
        )
        if pd.notna(row.get("Price")):
            rec["price"] = float(row["Price"])
        records.append(rec)

    return records


def write_cpt_jsonl(records: list[dict[str, Any]], output_path: Path | None = None) -> Path:
    output = output_path or OPENSTAT_OUTPUT_JSONL
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for rec in records:
            handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return output


def run(df: pd.DataFrame | None = None, *, csv_path: Path | None = None) -> int:
    """Write OpenSTAT CPT JSONL from a DataFrame or an existing CSV export."""
    console.rule("[bold cyan]OpenSTAT – Tabular to CPT[/bold cyan]")

    if df is None:
        source_csv = csv_path or OPENSTAT_TABLE_CSV
        console.print(f"[dim]Input CSV: {source_csv}[/dim]")
        if not source_csv.is_file():
            console.print("[yellow]No OpenSTAT table CSV found; skipping CPT step.[/yellow]")
            return 0
        df = pd.read_csv(source_csv)
    else:
        OPENSTAT_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(OPENSTAT_TABLE_CSV, index=False)
        console.print(f"[dim]Saved table CSV: {OPENSTAT_TABLE_CSV}[/dim]")

    records = tabular_to_cpt_records(df)
    if not records:
        console.print("[yellow]No tabular rows to convert; skipping CPT output.[/yellow]")
        return 0

    output = write_cpt_jsonl(records)
    console.print(f"[dim]Output: {output}[/dim]")
    console.print(f"[green]CPT sentences written:[/green] {len(records)}")
    return len(records)


if __name__ == "__main__":
    run()
