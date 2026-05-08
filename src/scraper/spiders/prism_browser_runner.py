"""PRiSM browser scrape orchestration (Scrapling)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from dotenv import load_dotenv
from rich.console import Console

from src.formatter.prism_browser_tables_csv import append_browser_tables_csv
from src.scraper.clients.prism_browser_sessions import (
    run_dynamic_session,
    run_fetch_session,
    run_stealth_session,
)
from src.scraper.parsers.prism_browser_page import collapse_blank_lines, safe_txt_name
from src.scraper.parsers.prism_browser_tables import extract_tables_from_page
from src.scraper.prism_browser_config import PrismBrowserConfig, load_prism_browser_config
from src.scraper.prism_urls import normalize_prism_target_url, parse_seed_urls
from src.services.checkpoint import load_json, save_checkpoint_json
from src.utils.net import require_internet
from src.utils.url_id import safe_id_from_url

load_dotenv()

try:
    from scrapling.fetchers import DynamicSession, FetcherSession, StealthyFetcher, StealthySession

    HAS_SCRAPLING = True
except ImportError:
    HAS_SCRAPLING = False
    DynamicSession = FetcherSession = StealthyFetcher = StealthySession = None  # type: ignore[misc, assignment]


def append_jsonl(record: dict[str, Any], path: Any) -> None:
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def urls_to_process(urls: list[str], scraped: set[str], cfg: PrismBrowserConfig, console: Console) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw in urls:
        norm = normalize_prism_target_url(raw, rewrite_dataproducts=cfg.rewrite_dataproducts)
        if cfg.resume_checkpoint and norm in scraped:
            short = norm[:80] + "…" if len(norm) > 80 else norm
            console.print(f"[dim]Skip (checkpoint): {short}[/dim]")
            continue
        if raw != norm:
            console.print(f"[dim]Target: {norm}[/dim] (from dataproducts wrapper)")
        out.append((raw, norm))
    return out


def make_persist_record(cfg: PrismBrowserConfig, scraped: set[str], checkpoint: dict, console: Console):
    def persist_record(raw_url: str, norm_url: str, title: str, text: str, page: Any | None = None) -> None:
        scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        corpus_written = False
        csv_written = False

        if cfg.export_tables_csv and page is not None:
            tables = extract_tables_from_page(page, norm_url, cfg)
            wide_rows = sum(
                1 for tab in tables for row in tab if len(row) > cfg.table_max_cols
            )
            if wide_rows:
                console.print(
                    f"[yellow]Truncating {wide_rows} wide rows to "
                    f"PRISM_BROWSER_TABLE_MAX_COLS={cfg.table_max_cols}.[/yellow]"
                )
            trimmed: list[list[list[str]]] = [
                [cells[: cfg.table_max_cols] for cells in tab] for tab in tables
            ]
            if trimmed:
                n = append_browser_tables_csv(
                    cfg.tables_csv_path,
                    source_url=norm_url,
                    page_title=title,
                    scraped_at=scraped_at,
                    tables=trimmed,
                    max_cols=cfg.table_max_cols,
                )
                csv_written = n > 0
                console.print(f"[green]Tables CSV[/green] — {n} row(s) → {cfg.tables_csv_path}")
            else:
                console.print("[yellow]No HTML tables found for CSV export (try selectors / JS settle).[/yellow]")

        if cfg.save_corpus:
            text_clean = collapse_blank_lines(text)
            if len(text_clean) < cfg.min_content_len:
                console.print(
                    f"[yellow]Text too short ({len(text_clean)} chars); skipping corpus JSONL/.txt.[/yellow]"
                )
            else:
                doc_id = safe_id_from_url(norm_url)
                record: dict[str, Any] = {
                    "text": text_clean,
                    "input": text_clean,
                    "content": text_clean,
                    "source": "prism",
                    "url": norm_url,
                    "title": title,
                    "doc_id": doc_id,
                }
                if raw_url != norm_url:
                    record["original_url"] = raw_url

                append_jsonl(record, cfg.jsonl_path)
                txt_path = cfg.txt_dir / safe_txt_name(norm_url)
                try:
                    cfg.txt_dir.mkdir(parents=True, exist_ok=True)
                    txt_path.write_text(text_clean, encoding="utf-8")
                except OSError:
                    pass
                corpus_written = True
                tshort = title[:60] + ("…" if len(title) > 60 else "")
                console.print(f"[green]Corpus[/green] — {len(text_clean)} chars, title={tshort!r}")

        if corpus_written or csv_written:
            scraped.add(norm_url)
            checkpoint["scraped_urls"] = sorted(scraped)
            save_checkpoint_json(cfg.checkpoint_path, checkpoint)

    return persist_record


@require_internet
def run_browser_scrape(cfg: PrismBrowserConfig | None = None, console: Console | None = None) -> None:
    cfg = cfg or load_prism_browser_config()
    console = console or Console()

    console.rule("[bold cyan]Prism – Scrape[/bold cyan]")
    console.print(f"[dim]JSONL: {cfg.jsonl_path}[/dim]")
    if cfg.export_tables_csv:
        console.print(f"[dim]Tables CSV: {cfg.tables_csv_path}[/dim]")
    console.print(
        f"[dim]save_corpus={cfg.save_corpus} | export_tables_csv={cfg.export_tables_csv} | "
        f"Scrapling mode={cfg.scrapling_mode} | solve_cloudflare={cfg.solve_cloudflare} | "
        f"rewrite_dataproducts={cfg.rewrite_dataproducts} | js_settle={cfg.js_settle_seconds}s[/dim]"
    )
    if cfg.content_selector:
        console.print(f"[dim]PRISM_CONTENT_SELECTOR={cfg.content_selector!r}[/dim]")

    urls = parse_seed_urls(cfg.urls_raw)
    if not urls:
        console.print(
            "[yellow]No valid PRISM_URL / PRISM_URLS. Example:\n"
            "  PRISM_URL=https://prism.philrice.gov.ph/dataproducts/[/yellow]"
        )
        return

    cfg.txt_dir.mkdir(parents=True, exist_ok=True)
    cfg.pdfs_dir.mkdir(parents=True, exist_ok=True)

    checkpoint: dict = load_json(cfg.checkpoint_path, default={"scraped_urls": []})
    scraped: set[str] = set(checkpoint.get("scraped_urls") or [])
    pending = urls_to_process(urls, scraped, cfg, console)
    if not pending:
        console.print("[dim]No new URLs to scrape.[/dim]")
        return

    if not HAS_SCRAPLING:
        console.print(
            "[red]Scrapling is not installed.[/red] "
            "[dim]uv sync --extra browser[/dim] then [dim]uv run scrapling install[/dim]"
        )
        return

    if cfg.scrapling_mode not in ("fetch", "stealth", "dynamic"):
        console.print(
            f"[red]Invalid PRISM_SCRAPLING_MODE={cfg.scrapling_mode!r}; use: fetch, stealth, dynamic.[/red]"
        )
        return

    console.print(
        f"[dim]Scrapling: mode={cfg.scrapling_mode} | impersonate={cfg.impersonate} | "
        f"http3={cfg.use_http3} | headless={cfg.headless}[/dim]"
    )

    persist_record = make_persist_record(cfg, scraped, checkpoint, console)

    assert FetcherSession is not None and StealthySession is not None
    assert DynamicSession is not None and StealthyFetcher is not None

    if cfg.scrapling_mode == "fetch":
        console.print(
            "[yellow]Warning: fetch mode is weak for wp-dynamicreports (JS). "
            "Try PRISM_SCRAPLING_MODE=stealth (default) or dynamic.[/yellow]"
        )
        run_fetch_session(pending, cfg, console, persist_record, FetcherSession)
    elif cfg.scrapling_mode == "stealth":
        run_stealth_session(pending, cfg, console, persist_record, StealthySession, StealthyFetcher)
    else:
        run_dynamic_session(pending, cfg, console, persist_record, DynamicSession)
