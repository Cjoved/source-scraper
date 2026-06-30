"""OpenSTAT scrape checkpoint + CSV merge helpers (URL-based, testable without Playwright)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse, urlunparse

import pandas as pd

from src.openstat.agri_corpus.scraper_utils import load_checkpoint, save_checkpoint

TABLE_COLUMNS = ["Geolocation", "Commodity Type", "Commodity", "Year", "Month", "Price"]
SOURCE_URL_COLUMN = "Source URL"
DEDUP_COLUMNS = ["Geolocation", "Commodity", "Year", "Month"]

DEFAULT_OPENSTAT_URLS = [
    "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__NFG/0032M4AFN01.px/",
    "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__2018/0042M4ARA01.px/table/tableViewLayout1/",
    "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__2018/0042M4ARA02.px/table/tableViewLayout1/",
    "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__2018/0042M4ARA03.px/table/tableViewLayout1/",
    "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__2018/0042M4ARA04.px/table/tableViewLayout1/",
    "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__2018/0042M4ARA05.px/table/tableViewLayout1/",
    "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__2018/0042M4ARA06.px/table/tableViewLayout1/",
    "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__2018/0042M4ARA07.px/table/tableViewLayout1/",
    "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__2018/0042M4ARA08.px/table/tableViewLayout1/",
    "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__2018/0042M4ARA09.px/table/tableViewLayout1/",
    "https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__2M__2018/0042M4ARA10.px/table/tableViewLayout1/",
]


def normalize_openstat_url(url: str) -> str:
    """Stable checkpoint key: strip whitespace, drop query/fragment, no trailing slash."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = (parsed.path or "").rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc.lower(), path, "", "", ""))


def get_openstat_urls(raw: str | None = None) -> list[str]:
    """Return OpenSTAT commodity URLs, using an optional comma-separated override."""
    value = raw if raw is not None else os.getenv("OPENSTAT_URLS", "")
    if value.strip():
        urls = [u for u in value.split(",") if u and u.strip()]
    else:
        urls = DEFAULT_OPENSTAT_URLS
    return [normalize_openstat_url(u) for u in urls if u and u.strip()]


def parse_urls_env(raw: str | None = None) -> list[str]:
    """Backward-compatible alias for older tests/imports."""
    return get_openstat_urls(raw)


def load_completed_urls(
    checkpoint_path: str | Path,
    url_list: Iterable[str] | None = None,
) -> set[str]:
    """
    Load completed PSA page URLs from checkpoint.

    Migrates legacy ``completed_url_indices`` using *url_list* order when present.
    """
    data = load_checkpoint(
        checkpoint_path,
        default={"completed_urls": [], "completed_url_indices": []},
    )
    raw_urls = data.get("completed_urls") or []
    if raw_urls:
        return {normalize_openstat_url(str(u)) for u in raw_urls if str(u).strip()}

    indices = data.get("completed_url_indices") or []
    if not indices:
        return set()

    ordered = list(url_list or parse_urls_env())
    migrated: set[str] = set()
    for idx in indices:
        try:
            i = int(idx)
        except (TypeError, ValueError):
            continue
        if 0 <= i < len(ordered):
            migrated.add(ordered[i])

    if migrated:
        save_completed_urls(checkpoint_path, migrated)
    return migrated


def save_completed_urls(checkpoint_path: str | Path, completed_urls: set[str] | Iterable[str]) -> None:
    normalized = sorted({normalize_openstat_url(u) for u in completed_urls if normalize_openstat_url(u)})
    save_checkpoint(
        checkpoint_path,
        {"completed_urls": normalized},
    )


def tag_frames_with_source_url(frames: list[pd.DataFrame], source_url: str) -> list[pd.DataFrame]:
    """Attach Source URL column so resume can replace per commodity page."""
    norm = normalize_openstat_url(source_url)
    tagged: list[pd.DataFrame] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        copy = frame.copy()
        copy[SOURCE_URL_COLUMN] = norm
        tagged.append(copy)
    return tagged


def _order_columns(df: pd.DataFrame) -> pd.DataFrame:
    if "Commodity" not in df.columns:
        df = df.copy()
        df["Commodity"] = df.get("Commodity Type", "N/A")
    cols = [c for c in TABLE_COLUMNS if c in df.columns]
    if SOURCE_URL_COLUMN in df.columns:
        cols.append(SOURCE_URL_COLUMN)
    extra = [c for c in df.columns if c not in cols]
    return df[cols + extra]


def _dedupe_price_rows(df: pd.DataFrame) -> pd.DataFrame:
    subset = [c for c in DEDUP_COLUMNS if c in df.columns]
    if not subset:
        return df
    return df.drop_duplicates(subset=subset, keep="last").reset_index(drop=True)


def merge_and_save_table_csv(
    new_frames: list[pd.DataFrame],
    *,
    table_csv_path: str | Path,
    completed_urls_before_run: set[str],
    urls_updated_this_run: set[str],
    resume: bool,
) -> pd.DataFrame | None:
    """
    Build final OpenSTAT table CSV.

    Resume mode keeps rows for skipped URLs and replaces rows for URLs scraped this run.
    Full run (resume=False) writes only *new_frames* (full replace).
    """
    path = Path(table_csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    new_parts = [f for f in new_frames if f is not None and not f.empty]
    new_df = pd.concat(new_parts, ignore_index=True) if new_parts else pd.DataFrame()

    if not resume:
        if new_df.empty:
            return None
        final_df = _dedupe_price_rows(_order_columns(new_df))
        final_df.to_csv(path, index=False)
        return final_df

    existing = pd.DataFrame()
    if path.is_file() and path.stat().st_size > 0:
        try:
            existing = pd.read_csv(path)
        except Exception:
            existing = pd.DataFrame()

    updated_norm = {normalize_openstat_url(u) for u in urls_updated_this_run}

    if existing.empty:
        if new_df.empty:
            return None
        final_df = _dedupe_price_rows(_order_columns(new_df))
        final_df.to_csv(path, index=False)
        return final_df

    if SOURCE_URL_COLUMN in existing.columns and updated_norm:
        existing[SOURCE_URL_COLUMN] = existing[SOURCE_URL_COLUMN].astype(str).map(normalize_openstat_url)
        kept = existing[~existing[SOURCE_URL_COLUMN].isin(updated_norm)]
        parts = [kept] if not kept.empty else []
        if not new_df.empty:
            parts.append(new_df)
        final_df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    elif not new_df.empty:
        final_df = pd.concat([existing, new_df], ignore_index=True)
    else:
        final_df = existing

    if final_df.empty:
        return None

    final_df = _dedupe_price_rows(_order_columns(final_df))
    final_df.to_csv(path, index=False)
    return final_df
