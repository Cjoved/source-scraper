"""OpenSTAT tabular data → CPT sentence records.

Converts long-format PSA farmgate price tables (one row per geo/commodity/month)
into natural-language CPT JSONL suitable for continued pre-training.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console

from src.services.config import data_path
from src.utils.cpt import make_cpt_record
from src.utils.text_chunk import chunk_text

console = Console()

SOURCE_NAME = "openstat"
SOURCE_NAME_RAG = "openstat_rag"
OPENSTAT_PROCESSED_DIR = data_path("openstat_processed")
OPENSTAT_TABLE_CSV = OPENSTAT_PROCESSED_DIR / "openstat_table.csv"
OPENSTAT_OUTPUT_JSONL = OPENSTAT_PROCESSED_DIR / "openstat_corpus.jsonl"
OPENSTAT_RAG_JSONL = OPENSTAT_PROCESSED_DIR / "openstat_corpus_rag.jsonl"
# Group monthly rows into passages, then chunk (~800–1500 chars is better for RAG than 1.7M one-liners).
OPENSTAT_RAG_CHUNK_CHARS = int(os.getenv("OPENSTAT_RAG_CHUNK_CHARS", "1200"))
WRITE_LINE_CORPUS = os.getenv("OPENSTAT_WRITE_LINE_CORPUS", "true").strip().lower() in (
    "true",
    "1",
    "yes",
)
WRITE_RAG_CORPUS = os.getenv("OPENSTAT_WRITE_RAG_CORPUS", "true").strip().lower() in (
    "true",
    "1",
    "yes",
)

_MONTH_ORDER = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

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


def _month_sort_key(month: str) -> tuple[int, str]:
    key = str(month or "").strip().lower()
    return (_MONTH_ORDER.get(key, 99), key)


def _group_passage(group: pd.DataFrame) -> str:
    """One geo + commodity + year → multi-sentence passage for embedding/RAG."""
    if group.empty:
        return ""

    work = group.copy()
    if "Month" in work.columns:
        work["_month_sort"] = work["Month"].astype(str).map(
            lambda m: _month_sort_key(m)[0]
        )
        work = work.sort_values(["Year", "_month_sort", "Month"], kind="stable")
    else:
        work = work.sort_values(["Year"], kind="stable")

    first = work.iloc[0]
    geo = str(first.get("Geolocation") or "").strip() or "unknown location"
    commodity = str(first.get("Commodity") or first.get("Commodity Type") or "commodity").strip()
    ctype = str(first.get("Commodity Type") or "").strip()
    year_val = first.get("Year")
    year_text = str(int(year_val)) if pd.notna(year_val) else "unknown year"
    type_clause = f" ({ctype})" if ctype and ctype != commodity else ""

    header = (
        f"PSA OpenSTAT farmgate price data for {commodity}{type_clause} in {geo}, "
        f"calendar year {year_text}. Source: Philippine Statistics Authority (openstat.psa.gov.ph). "
        f"Unit: Philippine pesos (PHP) per kilogram."
    )
    lines = [header]
    for _, row in work.iterrows():
        if pd.notna(row.get("Price")):
            lines.append(row_to_sentence(row))

    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def tabular_to_rag_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """
    Aggregate rows into geo/commodity/year passages, chunk for RAG/Qdrant indexing.
    Much smaller and more useful than one JSONL line per price cell.
    """
    prepared = _prepare_dataframe(df)
    if prepared.empty:
        return []

    group_cols = ["Geolocation", "Commodity", "Commodity Type", "Year"]
    for col in group_cols:
        if col not in prepared.columns:
            prepared[col] = ""

    records: list[dict[str, Any]] = []
    grouped = prepared.groupby(group_cols, dropna=False, sort=False)

    for key, group in grouped:
        passage = _group_passage(group)
        if not passage:
            continue

        geo, commodity, ctype, year = key
        chunks = (
            chunk_text(passage, OPENSTAT_RAG_CHUNK_CHARS)
            if OPENSTAT_RAG_CHUNK_CHARS > 0
            else [passage]
        )
        year_tok = _safe_token(year, "year")
        base_id = (
            f"openstat_rag_{_safe_token(geo, 'geo')}_{_safe_token(commodity, 'commodity')}_{year_tok}"
        )
        title = f"PSA farmgate prices: {commodity} in {geo}, {year_tok}"

        for chunk_idx, chunk in enumerate(chunks):
            doc_id = base_id if len(chunks) == 1 else f"{base_id}_c{chunk_idx}"
            rec = make_cpt_record(chunk, SOURCE_NAME_RAG, doc_id, title=title)
            rec.update(
                {
                    "geolocation": str(geo or "").strip(),
                    "commodity": str(commodity or "").strip(),
                    "commodity_type": str(ctype or "").strip(),
                    "year": int(year) if pd.notna(year) and str(year).strip() not in ("", "nan") else None,
                    "chunk_index": chunk_idx,
                    "chunk_count": len(chunks),
                }
            )
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

    line_count = 0
    rag_count = 0

    if WRITE_LINE_CORPUS:
        line_records = tabular_to_cpt_records(df)
        if line_records:
            out = write_cpt_jsonl(line_records, OPENSTAT_OUTPUT_JSONL)
            line_count = len(line_records)
            console.print(f"[dim]Line-level CPT: {out}[/dim]")
            console.print(f"[green]CPT sentences (1 row = 1 line):[/green] {line_count}")

    if WRITE_RAG_CORPUS:
        rag_records = tabular_to_rag_records(df)
        if rag_records:
            rag_out = write_cpt_jsonl(rag_records, OPENSTAT_RAG_JSONL)
            rag_count = len(rag_records)
            console.print(f"[dim]RAG corpus: {rag_out}[/dim]")
            console.print(
                f"[green]RAG chunks (geo×commodity×year, ~{OPENSTAT_RAG_CHUNK_CHARS} chars):[/green] {rag_count}"
            )

    if line_count == 0 and rag_count == 0:
        console.print("[yellow]No tabular rows to convert; skipping CPT output.[/yellow]")
        return 0

    return rag_count or line_count


if __name__ == "__main__":
    run()
