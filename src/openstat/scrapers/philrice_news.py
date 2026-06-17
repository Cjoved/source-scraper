"""
PhilRice News scraper – bawat article: text mula title hanggang (kasama) ang
"HOW DOES THIS POST MAKE YOU FEEL?" at mga percentage.
Filename = article title + posted date (e.g. ``Rice training expands support_2026-03-11.txt``).
"""
from playwright.sync_api import sync_playwright
from src.openstat.agri_corpus.scraper_utils import load_checkpoint, save_checkpoint
from src.openstat.utils import require_internet
from src.openstat.config import data_path
from dotenv import load_dotenv
from rich.console import Console
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
import os
import re
import time
import urllib.parse

from src.openstat.utils.stealth import apply_page_stealth, stealth_available

HAS_STEALTH = stealth_available()

load_dotenv()
console = Console()

PHILRICE_NEWS_URL = "https://www.philrice.gov.ph/news/"
PHILRICE_NEWS_DIR = data_path("philrice_news")
CHECKPOINT_PATH = data_path("checkpoints", "philrice_news_checkpoint.json")

DELAY_PAGE = int(os.getenv("PHILRICE_NEWS_DELAY", "6"))
DELAY_ARTICLE = int(os.getenv("PHILRICE_NEWS_ARTICLE_DELAY", "8"))
POST_GOTO_MS = int(os.getenv("PHILRICE_NEWS_POST_GOTO_MS", "5000"))
LISTING_SETTLE_MS = int(os.getenv("PHILRICE_NEWS_LISTING_SETTLE_MS", "6000"))
PAGE_TIMEOUT_MS = int(os.getenv("PHILRICE_NEWS_TIMEOUT_MS", "90000"))
GOTO_RETRIES = int(os.getenv("PHILRICE_NEWS_GOTO_RETRIES", "3"))

_MONTH = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _goto_with_retry(page, url: str, *, label: str = "page") -> object | None:
    """PhilRice gov.ph is often slow — retry with relaxed wait_until on later attempts."""
    wait_modes = ("domcontentloaded", "domcontentloaded", "commit")
    last_exc: Exception | None = None
    for attempt in range(1, GOTO_RETRIES + 1):
        wait_until = wait_modes[min(attempt - 1, len(wait_modes) - 1)]
        try:
            return page.goto(url, wait_until=wait_until, timeout=PAGE_TIMEOUT_MS)
        except Exception as exc:
            last_exc = exc
            console.print(
                f"[yellow]  {label} load attempt {attempt}/{GOTO_RETRIES} failed "
                f"({wait_until}): {exc}[/yellow]"
            )
            if attempt < GOTO_RETRIES:
                time.sleep(DELAY_PAGE * attempt)
    if last_exc is not None:
        raise last_exc
    return None


def _parse_posted_date(page) -> str | None:
    """
    Hanapin sa page ang "Posted on Mar - 11 - 2026" (o POSTED ON / March 11, 2026) at i-parse to MM-DD-YY.
    Returns e.g. "03-11-26" o None kung wala.
    """
    try:
        full = page.locator("main, article, .content, .entry-content, .post-content, [class*='post']").first.inner_text() or ""
        # Posted on Mar - 11 - 2026 (actual PhilRice format)
        m = re.search(r"Posted\s+on\s+([A-Za-z]+)\s*[-–]\s*(\d+)\s*[-–]\s*(\d{4})", full, re.IGNORECASE)
        if not m:
            m = re.search(r"POSTED\s+ON\s+([A-Za-z]+)\s*[-–]\s*(\d+)\s*[-–]\s*(\d{4})", full, re.IGNORECASE)
        if not m:
            m = re.search(r"Posted\s+on\s+([A-Za-z]+)\s+(\d+)\s*,?\s*(\d{4})", full, re.IGNORECASE)
        if not m:
            m = re.search(r"([A-Za-z]{3,9})\s*[-–]\s*(\d{1,2})\s*[-–]\s*(\d{4})", full)
        if m:
            mon, day, year = m.group(1).strip()[:3].lower(), m.group(2).strip(), m.group(3).strip()
            mm = _MONTH.get(mon, "01")
            dd = day.zfill(2) if len(day) <= 2 else day[:2]
            yy = year[-2:] if len(year) == 4 else year
            return f"{mm}-{dd}-{yy}"
    except Exception:
        pass
    return None


def _extract_article_text_to_feel_section(page) -> str:
    """
    Kunin text mula title hanggang (kasama) ang "How does this post make you feel?" at mood list
    (Excited, Fascinated, Amused, Bored, Sad, Angry). Hihinto bago "Leave a Reply".
    """
    try:
        for sel in ["main", "article", ".content", ".entry-content", ".post-content", "#content"]:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            full = loc.inner_text() or ""
            if len(full) < 50:
                continue
            # Tapusin bago "Leave a Reply" (PhilRice format) para kasama lang title → mood section
            leave_idx = full.find("Leave a Reply")
            if leave_idx == -1:
                leave_idx = full.find("### Leave a Reply")
            if leave_idx >= 0:
                full = full[:leave_idx].strip()

            # Siguraduhing kasama hanggang "How does this post make you feel?" + mood list (hanggang Angry)
            feel = "How does this post make you feel"
            idx = full.upper().find(feel.upper())
            if idx >= 0:
                rest = full[idx:]
                # Last mood sa PhilRice list ay "Angry" – include hanggang doon (o hanggang may 0% kung visible)
                end_m = re.search(r".*?(?:ANGRY|SAD|BORED|AMUSED|FASCINATED|EXCITED)\s*\d+\s*%", rest, re.DOTALL | re.IGNORECASE)
                if end_m:
                    full = full[: idx + end_m.end()].strip()
                else:
                    # Walang percentage sa text: hanggang last "Angry" (last item sa mood list)
                    last_angry = rest.upper().rfind("ANGRY")
                    if last_angry >= 0:
                        full = full[: idx + last_angry + 5].strip()  # +5 = len("Angry")
                    else:
                        full = full[: idx + min(len(rest), 350)].strip()
            return full.strip()
    except Exception as e:
        console.print(f"[yellow]extract_article_text: {e}[/yellow]")
    return ""


def _posted_date_to_iso(posted_mm_dd_yy: str) -> str:
    """Convert MM-DD-YY (from page) to YYYY-MM-DD for filenames."""
    parts = posted_mm_dd_yy.split("-")
    if len(parts) != 3:
        return posted_mm_dd_yy
    mm, dd, yy = parts
    century = "20" if len(yy) == 2 else ""
    return f"{century}{yy}-{mm}-{dd}"


def _safe_filename_from_title_and_date(
    title: str,
    posted_mm_dd_yy: str,
    url: str,
    existing: set[str],
) -> str:
    """
    Readable .txt name from headline + posted date.
    Collisions get ``_2``, ``_3``, … (same title/date or resume runs).
    """
    date_part = _posted_date_to_iso(posted_mm_dd_yy)
    safe_title = ""
    if title and title.strip():
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", title.strip())
        safe_title = re.sub(r"\s+", " ", safe_title).strip()[:100]

    if not safe_title:
        try:
            path = (urllib.parse.urlparse(url).path or "").strip("/")
            slug = path.replace("/", "_").strip("_") if path else ""
            safe_title = re.sub(r"[^\w\-_.]", "_", slug)[:100] if slug else ""
        except Exception:
            safe_title = ""
    if not safe_title:
        safe_title = "philrice_news_article"

    base = f"{safe_title}_{date_part}"
    candidate = f"{base}.txt"
    if candidate not in existing:
        existing.add(candidate)
        return candidate

    n = 2
    while True:
        candidate = f"{base}_{n}.txt"
        if candidate not in existing:
            existing.add(candidate)
            return candidate
        n += 1


SCRAPE_STATUS_PATH = data_path("checkpoints", "philrice_news_scrape_status.json")


@dataclass(frozen=True)
class PhilRiceNewsScrapeStatus:
    site_total: int
    verified_urls: int
    dead_urls: int
    txt_files: int
    fetched_this_run: int
    skipped_checkpoint: int
    incomplete: bool


def _http_response_not_found(response: object | None) -> bool:
    status = getattr(response, "status", None)
    return isinstance(status, int) and status >= 400


def _page_is_not_found(page) -> bool:
    """Detect nginx/WordPress 404 pages (Playwright does not throw on HTTP 404)."""
    try:
        title = (page.title() or "").lower()
        if "404" in title and "not found" in title:
            return True
        body = (page.locator("body").inner_text(timeout=3000) or "").lower()[:800]
        if "404 not found" in body:
            return True
    except Exception:
        pass
    return False


def _stream_mode() -> bool:
    from src.openstat.services import philrice_news as processing

    return processing.stream_process_enabled()


def _load_checkpoint_state() -> tuple[list[str], dict[str, str], set[str], dict[str, str]]:
    """
    Load checkpoint and verify each URL still has its .txt on disk (batch mode).

    Stream mode trusts url_to_file without requiring .txt on disk.
    Legacy checkpoints (scraped_urls only, no url_to_file) are not trusted.
    """
    data = load_checkpoint(
        CHECKPOINT_PATH,
        default={"scraped_urls": [], "url_to_file": {}, "url_to_title": {}, "dead_urls": []},
    )
    dead_raw = data.get("dead_urls") or []
    dead_urls = {str(u) for u in dead_raw} if isinstance(dead_raw, list) else set()
    url_to_file_raw = data.get("url_to_file") or {}
    url_to_file = (
        {str(k): str(v) for k, v in url_to_file_raw.items()}
        if isinstance(url_to_file_raw, dict)
        else {}
    )
    url_to_title_raw = data.get("url_to_title") or {}
    url_to_title = (
        {str(k): str(v) for k, v in url_to_title_raw.items()}
        if isinstance(url_to_title_raw, dict)
        else {}
    )
    legacy_urls = data.get("scraped_urls") or []
    news_dir = Path(PHILRICE_NEWS_DIR)

    if legacy_urls and not url_to_file:
        txt_count = len(list(news_dir.glob("*.txt")))
        console.print(
            f"[yellow]Legacy checkpoint ({len(legacy_urls)} URLs) has no file map — "
            f"only {txt_count} .txt on disk. Ignoring stale URL list; will re-fetch missing articles.[/yellow]"
        )
        return [], {}, dead_urls, {}

    if _stream_mode() and url_to_file:
        verified_urls = sorted(url_to_file.keys())
        return verified_urls, dict(url_to_file), dead_urls, dict(url_to_title)

    verified_urls: list[str] = []
    verified_map: dict[str, str] = {}
    missing_files = 0
    for url, fname in url_to_file.items():
        if (news_dir / fname).is_file():
            verified_urls.append(url)
            verified_map[url] = fname
        else:
            missing_files += 1

    if missing_files:
        console.print(
            f"[yellow]Checkpoint repair: {missing_files} URL(s) had no .txt — "
            f"will re-fetch on this run.[/yellow]"
        )
        _save_checkpoint_state(verified_urls, verified_map, dead_urls, url_to_title)

    return verified_urls, verified_map, dead_urls, url_to_title


def _save_checkpoint_state(
    scraped_urls: list[str],
    url_to_file: dict[str, str],
    dead_urls: set[str] | list[str] | None = None,
    url_to_title: dict[str, str] | None = None,
) -> None:
    dead_list = sorted(set(dead_urls or []))
    title_map = url_to_title or {}
    save_checkpoint(
        CHECKPOINT_PATH,
        {
            "scraped_urls": sorted(set(scraped_urls)),
            "url_to_file": {u: url_to_file[u] for u in scraped_urls if u in url_to_file},
            "url_to_title": {u: title_map[u] for u in scraped_urls if u in title_map},
            "dead_urls": dead_list,
        },
    )


def _write_scrape_status(status: PhilRiceNewsScrapeStatus) -> None:
    import json

    path = Path(SCRAPE_STATUS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "site_total": status.site_total,
                "verified_urls": status.verified_urls,
                "txt_files": status.txt_files,
                "fetched_this_run": status.fetched_this_run,
                "skipped_checkpoint": status.skipped_checkpoint,
                "dead_urls": status.dead_urls,
                "incomplete": status.incomplete,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _load_scraped_urls() -> list[str]:
    urls, _, _, _ = _load_checkpoint_state()
    return urls


def _save_checkpoint(
    scraped_urls: list[str],
    url_to_file: dict[str, str] | None = None,
    dead_urls: set[str] | None = None,
    url_to_title: dict[str, str] | None = None,
) -> None:
    if url_to_file is None or dead_urls is None or url_to_title is None:
        _, url_to_file_loaded, dead_loaded, title_loaded = _load_checkpoint_state()
        if url_to_file is None:
            url_to_file = url_to_file_loaded
        if dead_urls is None:
            dead_urls = dead_loaded
        if url_to_title is None:
            url_to_title = title_loaded
    _save_checkpoint_state(scraped_urls, url_to_file, dead_urls, url_to_title)


def _existing_txt_filenames(news_dir: Path | None = None) -> set[str]:
    """Filenames already on disk — used to avoid overwriting on resume."""
    root = news_dir or Path(PHILRICE_NEWS_DIR)
    if not root.is_dir():
        return set()
    return {path.name for path in root.glob("*.txt")}


def _collect_news_entries_on_page(page) -> list[tuple[str, str]]:
    """
    Sa kasalukuyang page (news listing), kunin lahat ng news article link (title + url).
    PhilRice article URLs ay philrice.gov.ph/<slug>/ (WALANG /news/ sa path), kaya hindi lang
    a[href*='/news/'] ang gamit – kukunin lahat ng same-domain link sa main na mukhang headline.
    """
    entries = []
    seen_url = set()
    try:
        # Main content area – PhilRice article links: philrice.gov.ph/slug/ (hindi /news/slug/)
        for container in ["main", "#content", ".content", "article", "[role='main']"]:
            links = page.locator(f"{container} a[href^='https://www.philrice.gov.ph/'], {container} a[href^='http://www.philrice.gov.ph/']")
            n = links.count()
            for i in range(n):
                try:
                    a = links.nth(i)
                    href = a.get_attribute("href")
                    if not href:
                        continue
                    href = href.split("?")[0].rstrip("/")
                    if href in seen_url:
                        continue
                    text = (a.inner_text() or "").strip()
                    if len(text) < 15:
                        continue
                    # Iwasan: nav/home, listing page mismo, downloads, about, contact
                    lower = href.lower()
                    if "/news/?" in lower or lower.endswith("/news") or lower.endswith("/news/"):
                        continue
                    if any(x in lower for x in ["/downloads", "/about", "/contact", "/careers", "/bids", "/links", "/products", "/services", "/impact", "/stories"]):
                        continue
                    # Mukhang article: may path na slug (e.g. /training-expands-extension-support...)
                    path = href.replace("https://www.philrice.gov.ph", "").replace("http://www.philrice.gov.ph", "").strip("/")
                    if not path or "/" in path:
                        continue
                    seen_url.add(href)
                    entries.append((text, href))
                except Exception:
                    continue
            if entries:
                break
    except Exception as e:
        console.print(f"[yellow]collect_news_entries: {e}[/yellow]")
    return entries


def _go_to_next_page(page) -> bool:
    """I-click ang Next / » para sa next page. Returns True kung nakapunta sa bagong page."""
    try:
        current_url = page.url or ""
        # Una: rel="next" o text "Next" / "»" (huwag i-click ang "Previous" o page number)
        for sel in [
            "a[rel='next']",
            "a.next",
            ".pagination a:has-text('Next')",
            "a:has-text('Next')",
        ]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                href = loc.get_attribute("href")
                if not href or "#" in href:
                    continue
                loc.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                page.wait_for_timeout(2000)
                if page.url != current_url:
                    return True
                return False
        return False
    except Exception:
        return False


@require_internet
def run() -> PhilRiceNewsScrapeStatus:
    from src.openstat.services import philrice_news as processing

    console.rule("[bold cyan]PhilRice News – title hanggang HOW DOES THIS POST MAKE YOU FEEL + %")
    os.makedirs(PHILRICE_NEWS_DIR, exist_ok=True)
    scraped, url_to_file, dead_urls, url_to_title = _load_checkpoint_state()
    scraped_set = set(scraped)
    dead_this_run = 0
    existing_filenames = _existing_txt_filenames()
    txt_on_disk = len(existing_filenames)
    fetched_this_run = 0
    site_total = 0
    skipped_checkpoint = 0
    stream = processing.stream_process_enabled()
    corpus_f = None
    corpus_path = ""
    total_stream_records = 0

    if stream:
        console.print("[dim]PHILRICE_NEWS_STREAM_PROCESS=true — CPT during scrape.[/dim]")
        corpus_f, corpus_path = processing.open_corpus_for_stream()

    if scraped or dead_urls:
        disk_note = f"{txt_on_disk} .txt on disk" if not stream else "stream mode (no .txt retention)"
        console.print(
            f"[dim]Checkpoint: {len(scraped)} verified URL(s), {len(dead_urls)} dead/404, "
            f"{disk_note} ({CHECKPOINT_PATH})[/dim]"
        )
    console.print(
        f"[dim]Delays: listing={DELAY_PAGE}s, article={DELAY_ARTICLE}s, "
        f"post-goto={POST_GOTO_MS}ms[/dim]"
    )

    all_entries = []
    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=False, channel="chrome", args=launch_args)
        except Exception:
            try:
                browser = p.chromium.launch(headless=False, channel="msedge", args=launch_args)
            except Exception:
                browser = p.chromium.launch(headless=False, args=launch_args)

        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="en-PH",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        if HAS_STEALTH:
            apply_page_stealth(page)

        page.set_default_timeout(PAGE_TIMEOUT_MS)

        try:
            console.print(f"[bold]Listing: {PHILRICE_NEWS_URL}[/bold]")
            _goto_with_retry(page, PHILRICE_NEWS_URL, label="News listing")
            page.wait_for_timeout(LISTING_SETTLE_MS)
            try:
                page.wait_for_selector("main a[href], #content a[href], .content a[href]", timeout=10000)
            except Exception:
                pass

            seen_text = set()
            page_num = 1
            while True:
                entries = _collect_news_entries_on_page(page)
                added = 0
                for text, url in entries:
                    if text not in seen_text:
                        seen_text.add(text)
                        all_entries.append((text, url))
                        added += 1
                console.print(f"[green]  Page {page_num}: {len(entries)} links, +{added} new[/green]")

                if not _go_to_next_page(page):
                    break
                page_num += 1
                time.sleep(DELAY_PAGE)

            skipped = sum(1 for _, u in all_entries if u in scraped_set)
            skipped_checkpoint = skipped
            site_total = len(all_entries)
            dead_skipped = sum(1 for _, u in all_entries if u in dead_urls)
            to_scrape = [
                (t, u) for t, u in all_entries if u not in scraped_set and u not in dead_urls
            ]
            console.print(
                f"[bold]Listing: {len(all_entries)} articles — "
                f"{skipped} verified, {dead_skipped} dead/404, {len(to_scrape)} to fetch[/bold]"
            )

            for title_text, url in to_scrape:
                try:
                    response = _goto_with_retry(page, url, label="Article")
                    page.wait_for_timeout(POST_GOTO_MS)
                    if _http_response_not_found(response) or _page_is_not_found(page):
                        console.print(f"[yellow]  Dead link (404), skipping:[/yellow] {url}")
                        dead_urls.add(url)
                        dead_this_run += 1
                        _save_checkpoint(scraped, url_to_file, dead_urls, url_to_title)
                        continue
                    posted = _parse_posted_date(page)
                    if not posted:
                        posted = datetime.now().strftime("%m-%d-%y")
                    fname = _safe_filename_from_title_and_date(
                        title_text, posted, url, existing_filenames
                    )
                    body = _extract_article_text_to_feel_section(page)
                    if not body:
                        body = title_text + "\n\n(Content not extracted)"
                    if stream and corpus_f is not None:
                        total_stream_records += processing.ingest_article_to_corpus(
                            url, title_text, body, fname, corpus_f
                        )
                        console.print(f"[green]  {fname} (stream CPT)[/green]")
                    else:
                        out_path = os.path.join(PHILRICE_NEWS_DIR, fname)
                        with open(out_path, "w", encoding="utf-8") as f:
                            f.write(body)
                        console.print(f"[green]  {fname}[/green]")
                    if url not in scraped_set:
                        scraped.append(url)
                        scraped_set.add(url)
                        url_to_file[url] = fname
                        url_to_title[url] = title_text
                        fetched_this_run += 1
                    _save_checkpoint(scraped, url_to_file, dead_urls, url_to_title)
                except Exception as e:
                    console.print(f"[yellow]  Skip {url[:50]}...: {e}[/yellow]")
                time.sleep(DELAY_ARTICLE)

            _save_checkpoint(scraped, url_to_file, dead_urls, url_to_title)

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            _save_checkpoint(scraped, url_to_file, dead_urls, url_to_title)
            raise
        finally:
            if corpus_f is not None:
                corpus_f.close()
            page.close()
            browser.close()

    if stream and corpus_path:
        console.print(
            f"[dim]Stream corpus records this run: {total_stream_records} -> {corpus_path}[/dim]"
        )

    txt_on_disk = len(_existing_txt_filenames()) if not stream else 0
    verified = len(scraped_set)
    dead_count = len(dead_urls)
    accounted = verified + dead_count
    incomplete = site_total > 0 and accounted < site_total
    status = PhilRiceNewsScrapeStatus(
        site_total=site_total,
        verified_urls=verified,
        dead_urls=dead_count,
        txt_files=txt_on_disk,
        fetched_this_run=fetched_this_run,
        skipped_checkpoint=skipped_checkpoint,
        incomplete=incomplete,
    )
    _write_scrape_status(status)

    console.rule("[bold]PhilRice News – scrape summary[/bold]")
    console.print(f"Output → [cyan]{os.path.abspath(PHILRICE_NEWS_DIR)}[/cyan]")
    console.print(
        f"Site listing: [bold]{site_total}[/bold] | "
        f"Verified: [bold]{verified}[/bold] | "
        f"Dead/404: [bold]{dead_count}[/bold] | "
        f".txt on disk: [bold]{txt_on_disk}[/bold] | "
        f"Fetched this run: [bold]{fetched_this_run}[/bold]"
    )
    if dead_this_run:
        console.print(
            f"[dim]{dead_this_run} dead link(s) marked this run (removed from PhilRice site).[/dim]"
        )
    if incomplete:
        remaining = site_total - accounted
        console.print(
            f"[yellow]Scrape NOT complete — {remaining} article(s) still to fetch. "
            f"Re-run the same job to continue (checkpoint saves after each article).[/yellow]"
        )
    else:
        console.print(
            "[green]Scrape complete — all listing URLs accounted for "
            "(verified .txt or dead/404).[/green]"
        )
    return status


if __name__ == "__main__":
    run()
