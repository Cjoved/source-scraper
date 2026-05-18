"""Typed env-backed settings for PRiSM browser scrape."""

from __future__ import annotations

import os

from src.models import browser_model
from src.services.config import data_path

def _truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes")


def load_prism_browser_config() -> browser_model.PrismBrowserConfig:
    urls_raw = (os.getenv("PRISM_URLS") or os.getenv("PRISM_URL") or "").strip()
    mode = (os.getenv("PRISM_SCRAPLING_MODE") or "stealth").strip().lower()
    headless = os.getenv("PRISM_HEADLESS", os.getenv("HEADLESS", "true")).strip().lower() != "false"
    export_tables = _truthy("PRISM_BROWSER_TABLES_CSV")
    save_corpus = _truthy("PRISM_BROWSER_SAVE_CORPUS", "true")
    return browser_model.PrismBrowserConfig(
        urls_raw=urls_raw,
        scrapling_mode=mode,
        headless=headless,
        delay_page=float(os.getenv("PRISM_DELAY_PAGE", "2")),
        min_content_len=int(os.getenv("PRISM_MIN_CONTENT_LEN", "100")),
        resume_checkpoint=os.getenv("PRISM_RESUME_CHECKPOINT", "true").strip().lower()
        in ("true", "1", "yes"),
        impersonate=(os.getenv("PRISM_IMPERSONATE") or "chrome").strip(),
        use_http3=os.getenv("PRISM_HTTP3", "false").strip().lower() in ("true", "1", "yes"),
        solve_cloudflare=os.getenv("PRISM_SOLVE_CLOUDFLARE", "true").strip().lower()
        in ("true", "1", "yes"),
        content_selector=(os.getenv("PRISM_CONTENT_SELECTOR") or "").strip(),
        adaptive=os.getenv("PRISM_ADAPTIVE", "false").strip().lower() in ("true", "1", "yes"),
        auto_save=os.getenv("PRISM_AUTO_SAVE", "false").strip().lower() in ("true", "1", "yes"),
        stealth_fetcher_adaptive=os.getenv("PRISM_STEALTH_FETCHER_ADAPTIVE", "true").strip().lower()
        in ("true", "1", "yes"),
        rewrite_dataproducts=os.getenv("PRISM_REWRITE_DATAPRODUCTS_TO_APP", "true").strip().lower()
        in ("true", "1", "yes"),
        js_settle_seconds=float(os.getenv("PRISM_JS_SETTLE_SECONDS", "8")),
        save_corpus=save_corpus,
        export_tables_csv=export_tables,
        tables_csv_path=data_path("prism_processed", "prism_browser_tables.csv"),
        table_max_cols=int(os.getenv("PRISM_BROWSER_TABLE_MAX_COLS", "32")),
        jsonl_path=data_path("prism_processed", "prism_corpus.jsonl"),
        txt_dir=data_path("prism_txt"),
        pdfs_dir=data_path("prism_pdfs"),
        checkpoint_path=data_path("checkpoints", "prism_checkpoint.json"),
    )
