"""Facebook profile scrape: login, latest post, images, checkpoint, logout."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

from rich.console import Console

from src.formatter.fb_posts_jsonl import append_fb_post_jsonl
from src.models.fb_model import FbPageConfig, FbTopPost
from src.scraper.clients.fb_browser_session import (
    fb_fetch_profile,
    fb_login,
    fb_logout,
    is_logged_in,
    open_stealth_session,
)
from src.scraper.clients.fb_media import download_post_images, repo_relative_path
from src.scraper.fb_config import load_fb_page_config
from src.scraper.parsers.fb_profile_posts import parse_top_post_from_page
from src.scraper.spiders.fb_checkpoint import build_checkpoint_update, should_persist_post
from src.services.checkpoint import load_json, save_checkpoint_json
from src.services.config import data_path
from src.utils.net import require_internet

try:
    from scrapling.fetchers import StealthySession

    HAS_SCRAPLING = True
except ImportError:
    HAS_SCRAPLING = False
    StealthySession = None  # type: ignore[misc, assignment]


def _checked_at() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _save_debug_html(page: Any, console: Console) -> None:
    path = data_path("prism_processed", "fb_debug_last.html")
    path.parent.mkdir(parents=True, exist_ok=True)
    html = getattr(page, "html_content", None) or getattr(page, "text", None) or ""
    if not html and hasattr(page, "body"):
        html = str(page.body or "")
    if not html:
        console.print("[yellow]Debug HTML save skipped: empty page body.[/yellow]")
        return
    path.write_text(html if isinstance(html, str) else html.decode("utf-8", errors="replace"), encoding="utf-8")
    console.print(f"[dim]Debug HTML saved → {path}[/dim]")


def build_post_record(cfg: FbPageConfig, post: FbTopPost, image_paths: list[str]) -> dict[str, Any]:
    return {
        "source": "facebook",
        "profile_url": cfg.profile_url,
        "post_id": post.post_id,
        "permalink": post.permalink,
        "posted_at": post.posted_at,
        "posted_at_iso": post.posted_at_iso,
        "scraped_at": _checked_at(),
        "text": post.text,
        "image_urls": list(post.image_urls),
        "image_paths": image_paths,
    }


def run_fb_page_scrape(cfg: FbPageConfig | None = None, console: Console | None = None) -> int:
    cfg = cfg or load_fb_page_config()
    console = console or Console()

    console.rule("[bold cyan]Facebook – Profile (latest post)[/bold cyan]")
    console.print(f"[dim]Profile: {cfg.profile_url}[/dim]")
    console.print(f"[dim]JSONL: {cfg.output_jsonl_path}[/dim]")
    console.print(f"[dim]Images: {cfg.images_dir}[/dim]")

    if not cfg.email or not cfg.password:
        console.print("[red]FB_EMAIL and FB_PASSWORD are required.[/red]")
        return 1

    if not HAS_SCRAPLING or StealthySession is None:
        console.print(
            "[red]Scrapling is not installed.[/red] "
            "[dim]uv sync --extra browser[/dim] then [dim]uv run scrapling install[/dim]"
        )
        return 1

    if cfg.scrapling_mode != "stealth":
        console.print(
            f"[yellow]FB_SCRAPLING_MODE={cfg.scrapling_mode!r} not supported; using stealth.[/yellow]"
        )

    checkpoint: dict[str, Any] = load_json(
        cfg.checkpoint_path,
        default={"profile_url": cfg.profile_url, "last_post_id": None},
    )
    last_post_id = checkpoint.get("last_post_id")
    checked_at = _checked_at()

    with open_stealth_session(cfg) as session:
        try:
            fb_login(session, cfg, console)
            if not is_logged_in(session):
                console.print(
                    "[red]Not logged in after login step. "
                    "Set FB_HEADLESS=false to complete captcha manually.[/red]"
                )
                return 1
            extract_holder: list[FbTopPost] = []
            extract_note_holder: list[str] = []
            page = fb_fetch_profile(
                session, cfg, console, extract_holder, extract_note_holder
            )
            note = extract_note_holder[0] if extract_note_holder else ""
            if note:
                if note.startswith("other_posts"):
                    console.print(f"[green]Using Other posts section[/green] [dim]({note})[/dim]")
                elif "no_other_posts_marker" in note:
                    console.print(
                        f"[yellow]Other posts heading not found; fallback extract[/yellow] "
                        f"[dim]({note})[/dim]"
                    )
                else:
                    console.print(f"[dim]Extract strategy: {note}[/dim]")

            post = extract_holder[0] if extract_holder else parse_top_post_from_page(page, cfg.profile_url)

            if post is None:
                if "validation_failed" in note:
                    console.print(
                        "[yellow]Other posts section located but no article passed validation.[/yellow]"
                    )
                console.print(
                    "[yellow]No timeline post found on profile page.[/yellow]\n"
                    "[dim]Tip: confirm FB_EMAIL/FB_PASSWORD; try FB_HEADLESS=false; "
                    "set FB_DEBUG_SAVE_HTML=true to capture DOM.[/dim]"
                )
                if cfg.debug_save_html or "validation_failed" in note:
                    _save_debug_html(page, console)
                checkpoint["last_checked_at"] = checked_at
                save_checkpoint_json(cfg.checkpoint_path, checkpoint, add_updated=False)
                fb_logout(session, cfg, console)
                return 1

            console.print(f"[dim]Latest post_id={post.post_id!r}[/dim]")
            if post.posted_at:
                console.print(f"[dim]Posted: {post.posted_at}[/dim]")
            preview = post.text[:80] + ("…" if len(post.text) > 80 else "")
            if preview:
                console.print(f"[dim]Text: {preview}[/dim]")

            if not should_persist_post(last_post_id, post.post_id):
                console.print("[dim]No new post (checkpoint match). Skipping write.[/dim]")
                checkpoint["last_checked_at"] = checked_at
                save_checkpoint_json(cfg.checkpoint_path, checkpoint, add_updated=False)
                fb_logout(session, cfg, console)
                return 0

            image_paths: list[str] = []
            if cfg.download_images and post.image_urls:
                saved = download_post_images(session, cfg, post.post_id, post.image_urls)
                image_paths = [repo_relative_path(p) for p in saved]
                if saved:
                    console.print(f"[green]Images[/green] — {len(saved)} file(s) → {cfg.images_dir}")
                else:
                    console.print("[yellow]Image download failed or returned no files.[/yellow]")

            record = build_post_record(cfg, post, image_paths)
            append_fb_post_jsonl(cfg.output_jsonl_path, record)
            console.print(f"[green]JSONL[/green] — appended → {cfg.output_jsonl_path}")

            checkpoint.update(
                build_checkpoint_update(
                    cfg.profile_url,
                    post.post_id,
                    post.posted_at,
                    checked_at,
                    posted_at_iso=post.posted_at_iso,
                )
            )
            save_checkpoint_json(cfg.checkpoint_path, checkpoint, add_updated=False)

            fb_logout(session, cfg, console)
            return 0
        except Exception as e:
            console.print(f"[red]FB scrape failed: {e}[/red]")
            try:
                fb_logout(session, cfg, console)
            except Exception:
                pass
            return 1


@require_internet
def run_fb_page_job(console: Console | None = None) -> None:
    code = run_fb_page_scrape(console=console)
    if code != 0:
        sys.exit(code)
