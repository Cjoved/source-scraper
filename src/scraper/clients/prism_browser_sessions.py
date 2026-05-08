"""Scrapling session loops — fetch / stealth / dynamic."""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console

from src.scraper.parsers.prism_browser_page import extract_body_text, page_title
from src.scraper.prism_browser_config import PrismBrowserConfig
from src.scraper.prism_urls import is_prism_dynamic_app


def _maybe_js_settle(norm_url: str, cfg: PrismBrowserConfig, console: Console) -> None:
    if is_prism_dynamic_app(norm_url) and cfg.js_settle_seconds > 0:
        console.print(f"[dim]JS settle {cfg.js_settle_seconds}s (PRiSM app)…[/dim]")
        time.sleep(cfg.js_settle_seconds)


def process_scrapling_page(
    raw_url: str,
    norm_url: str,
    page: Any,
    cfg: PrismBrowserConfig,
    *,
    console: Console,
    persist_record: Any,
) -> None:
    try:
        title = page_title(page)
        text = extract_body_text(page, norm_url, cfg)
    except Exception as e:
        console.print(f"[red]Parse error: {e}[/red]")
        return
    persist_record(raw_url, norm_url, title, text, page)


def run_fetch_session(
    pending: list[tuple[str, str]],
    cfg: PrismBrowserConfig,
    console: Console,
    persist_record: Any,
    fetcher_session_cls: Any,
) -> None:
    session_kw: dict[str, Any] = {"impersonate": cfg.impersonate}
    if cfg.use_http3:
        session_kw["http3"] = True
    with fetcher_session_cls(**session_kw) as session:
        for raw, norm in pending:
            console.print(f"[bold]→[/bold] {norm}")
            try:
                page = session.get(norm, stealthy_headers=True)
            except Exception as e:
                console.print(f"[red]Fetch error: {e}[/red]")
                time.sleep(cfg.delay_page)
                continue
            _maybe_js_settle(norm, cfg, console)
            process_scrapling_page(raw, norm, page, cfg, console=console, persist_record=persist_record)
            time.sleep(cfg.delay_page)


def run_stealth_session(
    pending: list[tuple[str, str]],
    cfg: PrismBrowserConfig,
    console: Console,
    persist_record: Any,
    stealthy_session_cls: Any,
    stealthy_fetcher_cls: Any,
) -> None:
    if cfg.stealth_fetcher_adaptive:
        stealthy_fetcher_cls.adaptive = True
        console.print("[dim]StealthyFetcher.adaptive = True (class)[/dim]")
    session_kw: dict[str, Any] = {"headless": cfg.headless}
    if cfg.solve_cloudflare:
        session_kw["solve_cloudflare"] = True
        console.print("[dim]StealthySession: solve_cloudflare=True[/dim]")
    with stealthy_session_cls(**session_kw) as session:
        for raw, norm in pending:
            console.print(f"[bold]→[/bold] {norm}")
            try:
                try:
                    page = session.fetch(norm, google_search=False)
                except TypeError:
                    page = session.fetch(norm)
            except Exception as e:
                console.print(f"[red]Fetch error: {e}[/red]")
                time.sleep(cfg.delay_page)
                continue
            _maybe_js_settle(norm, cfg, console)
            process_scrapling_page(raw, norm, page, cfg, console=console, persist_record=persist_record)
            time.sleep(cfg.delay_page)


def run_dynamic_session(
    pending: list[tuple[str, str]],
    cfg: PrismBrowserConfig,
    console: Console,
    persist_record: Any,
    dynamic_session_cls: Any,
) -> None:
    session_kw: dict[str, Any] = {
        "headless": cfg.headless,
        "disable_resources": False,
        "network_idle": True,
    }
    with dynamic_session_cls(**session_kw) as session:
        for raw, norm in pending:
            console.print(f"[bold]→[/bold] {norm}")
            try:
                try:
                    page = session.fetch(norm, network_idle=True)
                except TypeError:
                    page = session.fetch(norm)
            except Exception as e:
                console.print(f"[red]Fetch error: {e}[/red]")
                time.sleep(cfg.delay_page)
                continue
            _maybe_js_settle(norm, cfg, console)
            process_scrapling_page(raw, norm, page, cfg, console=console, persist_record=persist_record)
            time.sleep(cfg.delay_page)
