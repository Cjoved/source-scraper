"""
PRiSM scrapers — modular layout.

Jobs (`PRISM_JOB`):
- `export_yield_csv` / `export_yield` — bulk yield via HTTP POST (no browser).
- `browser_csv` / `browser_tables_csv` — Scrapling page load → extract `<table>` → CSV
  (optional corpus via `PRISM_BROWSER_SAVE_CORPUS=true`).
- (unset) — browser scrape; set `PRISM_BROWSER_TABLES_CSV=true` to also emit tables CSV.

Install:
  uv sync
  uv sync --extra browser   # adds scrapling[all]
  uv run scrapling install  # browser binaries for Scrapling
"""

from __future__ import annotations

import os
from dataclasses import replace

from dotenv import load_dotenv
from rich.console import Console

from src.services.config import data_path
from src.scraper.prism_browser_config import load_prism_browser_config
from src.scraper.spiders.prism_browser_runner import run_browser_scrape
from src.scraper.spiders.prism_yield_runner import run_yield_export
from src.scraper.clients.prism_yield_http import PrismYieldHttpClient
from src.utils.net import require_internet

load_dotenv()


@require_internet
def run_yield_export_job(console: Console | None = None) -> None:
    console = console or Console()
    console.rule("[bold cyan]Prism – Yield CSV (HTTP)[/bold cyan]")
    client = PrismYieldHttpClient(
        delay=float(os.getenv("PRISM_EXPORT_DELAY", "1.0")),
        jitter=float(os.getenv("PRISM_EXPORT_JITTER", "0.55")),
        retries=int(os.getenv("PRISM_EXPORT_RETRIES", "5")),
        timeout=int(os.getenv("PRISM_EXPORT_TIMEOUT", "90")),
        console=console,
    )
    run_yield_export(
        csv_path=data_path("prism_processed", "prism_yield_export.csv"),
        checkpoint_path=data_path("checkpoints", "prism_yield_export_checkpoint.json"),
        client=client,
        year_min=int(os.getenv("PRISM_EXPORT_YEAR_MIN", "2018")),
        year_max=int(os.getenv("PRISM_EXPORT_YEAR_MAX", "2026")),
        cooldown_every=int(os.getenv("PRISM_EXPORT_COOLDOWN_EVERY", "75")),
        cooldown_seconds=float(os.getenv("PRISM_EXPORT_COOLDOWN_SECONDS", "12")),
        console=console,
    )


def run() -> None:
    job = (os.getenv("PRISM_JOB") or "").strip().lower()
    if job in ("export_yield_csv", "export_yield"):
        run_yield_export_job()
        return
    if job in ("browser_csv", "browser_tables_csv"):
        base = load_prism_browser_config()
        cfg = replace(
            base,
            export_tables_csv=True,
            save_corpus=os.getenv("PRISM_BROWSER_SAVE_CORPUS", "false").strip().lower()
            in ("true", "1", "yes"),
        )
        run_browser_scrape(cfg)
        from src.services.prism import run as run_prism_process

        run_prism_process()
        return
    run_browser_scrape()
    from src.services.prism import run as run_prism_process

    run_prism_process()
