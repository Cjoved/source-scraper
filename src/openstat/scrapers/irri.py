"""
IRRI Philippines scraper – bawat link: kunin text (main content) at/o i-download PDF kung may link.
Output: data/irri_processed/text/*.txt, data/irri_pdfs/*.pdf. Checkpoint/resume supported.
Filename: ``{article title}_{YYYY-MM-DD}.txt`` (saved per article as each listing page is processed).
"""
from playwright.sync_api import sync_playwright
from src.openstat.utils import require_internet
from src.openstat.config import data_path
from src.openstat.agri_corpus.scraper_utils import (
    normalize_url,
    load_checkpoint,
    save_checkpoint,
    safe_filename_from_url,
)
from dotenv import load_dotenv
from rich.console import Console
from datetime import datetime
from pathlib import Path
import os
import re
import json
import time
import random
import urllib.parse

from src.openstat.utils.stealth import apply_page_stealth, stealth_available

HAS_STEALTH = stealth_available()

load_dotenv()
console = Console()

IRRI_TEXT_DIR = data_path("irri_processed", "text")
IRRI_PDFS_DIR = data_path("irri_pdfs")
CHECKPOINT_PATH = data_path("checkpoints", "irri_checkpoint.json")

# Delay: pagkatapos i-download lahat sa current page, hintay bago next page (para di ma-detect)
DELAY_PDF = int(os.getenv("IRRI_DELAY_PDF", "2"))          # seconds between each PDF download
DELAY_AFTER_PAGE = int(os.getenv("IRRI_DELAY_AFTER_PAGE", "3"))  # after text + all PDFs on this page
DELAY_PAGE = int(os.getenv("IRRI_DELAY_PAGE", "6"))        # extra delay bago mag-next page (total = AFTER + PAGE)
# Kapag 403 (CloudFront block): wait bago retry, max retries. Taas mo kung madalas 403.
IRRI_RETRY_WAIT = int(os.getenv("IRRI_RETRY_WAIT", "40"))
IRRI_MAX_RETRIES = max(1, int(os.getenv("IRRI_MAX_RETRIES", "3")))
IRRI_RANDOM_EXTRA = int(os.getenv("IRRI_RANDOM_EXTRA", "8"))  # 0–N sec random delay (para di fixed pattern)

# Base URL for relative links
BASE_IRRI = "https://www.irri.org"
BASE_HDL = "https://hdl.handle.net"

# News listing: all news by default (no country filter). Set IRRI_SKIP_COUNTRY_SEARCH=false for Philippines only.
NEWS_LISTING_URL = "https://www.irri.org/news-and-events/news"
PHILIPPINES_NEWS_LISTING = "https://www.irri.org/news-and-events/news?country=Philippines"  # fallback kung Philippines filter
# Gamitin bundled Chromium muna (imbes na Chrome/Edge): .env IRRI_USE_CHROMIUM=true – subok kung 403 pa rin sa Chrome
IRRI_USE_CHROMIUM = os.getenv("IRRI_USE_CHROMIUM", "false").strip().lower() in ("true", "1", "yes")
# Cooldown bawat N listing pages (bago mag-next page): IRRI_COOLDOWN_EVERY_N_PAGES=6, IRRI_COOLDOWN_SECONDS=90
IRRI_COOLDOWN_EVERY_N_PAGES = max(0, int(os.getenv("IRRI_COOLDOWN_EVERY_N_PAGES", "6")))
IRRI_COOLDOWN_SECONDS = max(0, int(os.getenv("IRRI_COOLDOWN_SECONDS", "90")))


def _all_news_mode() -> bool:
    """Default: scrape all IRRI news (no Philippines country filter)."""
    return os.getenv("IRRI_SKIP_COUNTRY_SEARCH", "true").strip().lower() in ("true", "1", "yes")


def _irri_start_page() -> int:
    raw = os.getenv("IRRI_START_PAGE", "").strip()
    return max(1, int(raw)) if raw.isdigit() else 0

# Starter URL list: reserved kung gusto mong magdagdag pa later.
# By default, IRRI scraper kumukuha ng lahat ng news mula sa All News listing.
IRRI_URLS: list[str] = []

_MONTH = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}
IRRI_TITLE_SUFFIX = re.compile(
    r"\s*[_\|]\s*International Rice Research Institute\s*$",
    re.IGNORECASE,
)
_DATE_IN_TEXT = re.compile(
    r"(?:^|\n)\s*"
    r"(?:(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})"
    r"|([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})"
    r"|(\d{1,2})\s+([A-Za-z]+)\s+(\d{4}))",
    re.IGNORECASE,
)


def _month_to_mm(month: str) -> str:
    return _MONTH.get(month.strip()[:3].lower(), "01")


def _to_iso_date(year: str, month: str, day: str) -> str:
    mm = _month_to_mm(month)
    dd = day.zfill(2)
    return f"{year}-{mm}-{dd}"


def _parse_date_from_text(text: str) -> str | None:
    """Parse common IRRI article date lines into YYYY-MM-DD."""
    if not text:
        return None
    sample = text[:2500]
    match = _DATE_IN_TEXT.search(sample)
    if not match:
        return None
    groups = match.groups()
    if groups[0]:
        return _to_iso_date(groups[2], groups[1], groups[0])
    if groups[3]:
        return _to_iso_date(groups[5], groups[3], groups[4])
    if groups[6]:
        return _to_iso_date(groups[8], groups[7], groups[6])
    return None


def _parse_article_date(page, body_text: str = "") -> str | None:
    """Read article posted date from HTML time element or leading body text."""
    try:
        for sel in [
            "time[datetime]",
            ".field--name-field-date time",
            ".node__meta time",
            "article time",
        ]:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            dt = (loc.get_attribute("datetime") or "").strip()
            if len(dt) >= 10 and dt[4] == "-":
                return dt[:10]
    except Exception:
        pass
    return _parse_date_from_text(body_text)


def _clean_title_for_filename(title: str) -> str:
    t = IRRI_TITLE_SUFFIX.sub("", title or "").strip()
    return re.sub(r"\s+", " ", t)


def _safe_filename_from_title_and_date(
    title: str,
    date_iso: str,
    url: str,
    existing: set[str],
) -> str:
    """Readable .txt name: headline + YYYY-MM-DD; collisions get _2, _3, ..."""
    safe_title = ""
    cleaned = _clean_title_for_filename(title)
    if cleaned:
        safe_title = re.sub(r'[<>:"/\\|?*]', "_", cleaned)
        safe_title = re.sub(r"\s+", " ", safe_title).strip()[:100]

    if not safe_title:
        try:
            path = (urllib.parse.urlparse(url).path or "").strip("/")
            slug = path.replace("/", "_").strip("_") if path else ""
            safe_title = re.sub(r"[^\w\-_.]", "_", slug)[:100] if slug else ""
        except Exception:
            safe_title = ""
    if not safe_title:
        safe_title = "irri_article"

    date_part = date_iso or "unknown-date"
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


def _existing_txt_filenames(text_dir: Path | None = None) -> set[str]:
    root = text_dir or Path(IRRI_TEXT_DIR)
    if not root.is_dir():
        return set()
    return {path.name for path in root.glob("*.txt")}


def _extract_main_text(page) -> str:
    """
    Extract main article body only: walang nav, walang Related News section.
    Para sa news form pages (e.g. whats-next-climate); hdl/iba same selectors, then strip Related News.
    """
    raw = ""
    for sel in [
        ".field--body",
        "article .content",
        "article",
        "main",
        "#main-content",
        "[role='main']",
    ]:
        try:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            raw = (loc.inner_text() or "").strip()
            if len(raw) >= 100:
                break
        except Exception:
            continue
    if not raw:
        try:
            raw = page.locator("body").inner_text() or ""
            raw = raw.strip()
        except Exception:
            return ""
    # Huwag isama ang Related News pababa (nav at footer usually wala na sa main; Related News nasa loob)
    for marker in ["Related News", "## Related News", "Related news"]:
        if marker in raw:
            raw = raw.split(marker)[0].strip()
    return raw


def _collect_pdf_links(page, page_url: str) -> list[str]:
    """Collect PDF links from current page (irri.org and hdl.handle.net)."""
    out = []
    try:
        for a in page.locator("a[href]").all():
            href = a.get_attribute("href")
            if not href or not href.strip():
                continue
            full = normalize_url(href.strip(), page_url)
            if not full:
                continue
            lower = full.lower()
            if ".pdf" in lower:
                out.append(full)
            # hdl.handle.net: PDF / bitstream / books.irri.org download links
            if "hdl.handle.net" in page_url:
                if "cgspace.cgiar.org" in full and ("bitstream" in lower or "download" in lower):
                    out.append(full)
                if "books.irri.org" in full and ".pdf" in lower:
                    out.append(full)
    except Exception as e:
        console.print(f"[yellow]collect_pdf_links: {e}[/yellow]")
    return list(dict.fromkeys(out))  # unique order preserved


def _is_news_article_url(url: str) -> bool:
    """True kung irri.org/news-and-events/news/<slug> (article page, hindi listing)."""
    try:
        parsed = urllib.parse.urlparse(url)
        if "irri.org" not in (parsed.netloc or ""):
            return False
        path = (parsed.path or "").strip("/")
        # Article: /news-and-events/news/<slug> with non-empty slug
        if not path.startswith("news-and-events/news/"):
            return False
        rest = path.replace("news-and-events/news/", "", 1).strip("/")
        return bool(rest)
    except Exception:
        return False


def _go_to_next_listing_page(page) -> bool:
    """Click Next page / rel=next on news listing. Returns True kung may next page."""
    try:
        current = page.url or ""
        for sel in [
            "a[rel='next']",
            "a.pager__link--next",
            ".pagination a:has-text('Next')",
            "a:has-text('Next page')",
            "a:has-text('Next')",
        ]:
            loc = page.locator(sel).first
            if loc.count() == 0:
                continue
            href = loc.get_attribute("href")
            if not href or (href or "").strip().startswith("#"):
                continue
            loc.click()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
            if page.url != current:
                return True
            return False
        return False
    except Exception:
        return False


def _apply_country_and_search(page) -> bool:
    """
    Hanapin Country filter (native select o custom widget) → Philippines → pindutin Search.
    Pinag-lalagyan: exposed form (views-exposed-form) – Country at Search button doon.
    """
    try:
        page.wait_for_timeout(2500)
        # --- Country: pinag-lalagyan = edit-field-countries-ref-target-id (value Philippines = 18) ---
        country_set = False
        for sel in [
            'select#edit-field-countries-ref-target-id',
            'select[name="field_countries_ref_target_id"]',
            'select[data-drupal-selector="edit-field-countries-ref-target-id"]',
            'select[name="country"]',
            "select#edit-country",
            'select[id*="country"]',
            'select.form-select',
        ]:
            loc = page.locator(sel).first
            if loc.count() > 0:
                try:
                    loc.select_option(label="ALL")
                    console.print("[dim]  Country (select) -> Philippines[/dim]")
                    country_set = True
                    break
                except Exception:
                    try:
                        loc.select_option(value="18")  # Philippines value sa IRRI form
                        console.print("[dim]  Country (value 18) -> Philippines[/dim]")
                        country_set = True
                        break
                    except Exception:
                        try:
                            loc.select_option(value="Philippines")
                            console.print("[dim]  Country (value Philippines) -> Philippines[/dim]")
                            country_set = True
                            break
                        except Exception:
                            pass
                break
        # --- Kung hindi <select>: custom widget – click area ng Country then click "Philippines" ---
        if not country_set:
            for open_sel in [
                '[data-drupal-selector="edit-country"]',
                '.form-item-country',
                '.form-item--country',
                'label:has-text("Country")',
                '.views-exposed-form select',  # fallback
            ]:
                open_loc = page.locator(open_sel).first
                if open_loc.count() > 0:
                    try:
                        open_loc.click()
                        page.wait_for_timeout(600)
                        ph = page.get_by_role("option", name="Philippines").or_(page.locator('text="Philippines"').first)
                        if ph.count() > 0:
                            ph.first.click()
                            console.print("[dim]  Country (custom) -> Philippines[/dim]")
                            country_set = True
                            break
                    except Exception:
                        pass
            if not country_set:
                try:
                    page.locator('text="Philippines"').first.click()
                    console.print("[dim]  Clicked Philippines[/dim]")
                    country_set = True
                except Exception:
                    pass
        page.wait_for_timeout(500)
        # --- Search button: pinag-lalagyan = edit-submit-related-news ---
        search_clicked = False
        for sel in [
            'button#edit-submit-related-news',
            '[data-drupal-selector="edit-submit-related-news"]',
            'button[data-drupal-selector="edit-submit-related-news"]',
            '.views-exposed-form input[type="submit"]',
            '.views-exposed-form button[type="submit"]',
            '.form-actions input[type="submit"]',
            '.form-actions button[type="submit"]',
            'input[type="submit"][value="Search"]',
            'button:has-text("Search")',
            'button.form-submit',
            '[data-drupal-selector="edit-actions-submit"]',
            '#edit-actions-submit',
            'input.form-submit',
            'a.button:has-text("Search")',
            '[value="Search"]',
        ]:
            btn = page.locator(sel).first
            if btn.count() > 0:
                try:
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    console.print("[dim]  Clicked Search[/dim]")
                    search_clicked = True
                    break
                except Exception:
                    pass
        if not search_clicked:
            try:
                page.get_by_role("button", name="Search").click()
                console.print("[dim]  Clicked Search (role)[/dim]")
                search_clicked = True
            except Exception:
                pass
        if not search_clicked:
            try:
                page.locator('form').filter(has=page.locator('input[type="submit"], button[type="submit"]')).locator('input[type="submit"], button[type="submit"]').first.click()
                console.print("[dim]  Clicked submit in form[/dim]")
                search_clicked = True
            except Exception:
                pass
        if search_clicked:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            return True
        return False
    except Exception as e:
        console.print(f"[yellow]  Country/Search: {e}[/yellow]")
        return False


def _get_article_links_on_listing_page(page) -> list:
    """Kunin lahat ng news article links sa current listing page (order ng cards)."""
    out = []
    seen = set()
    try:
        for a in page.locator("a[href]").all():
            href = a.get_attribute("href")
            if not href or not href.strip():
                continue
            full = normalize_url(href.strip(), page.url)
            if not full or full in seen:
                continue
            if _is_news_article_url(full):
                seen.add(full)
                out.append(full)
    except Exception as e:
        console.print(f"[yellow]get_article_links: {e}[/yellow]")
    return out


def _open_listing_and_apply_search(page) -> bool:
    """Open news listing. Default: all news. Set IRRI_SKIP_COUNTRY_SEARCH=false for Philippines filter."""
    if not _goto_with_retry(page, NEWS_LISTING_URL):
        return False
    if _all_news_mode():
        console.print("[dim]  All News mode (no country filter)[/dim]")
        page.wait_for_timeout(3000)
        return True
    if not _apply_country_and_search(page):
        console.print("[dim]  Fallback: loading ?country=Philippines[/dim]")
        if not _goto_with_retry(page, PHILIPPINES_NEWS_LISTING):
            return False
        page.wait_for_timeout(3000)
    return True


def _download_pdf(context, pdf_url: str, folder: str, index: int) -> bool:
    """Download one PDF; return True if saved or already exists."""
    fname = safe_filename_from_url(pdf_url, max_len=160, suffix=".pdf")
    path = os.path.join(folder, fname)
    if os.path.isfile(path):
        console.print(f"[dim]Skip PDF (exists): {fname}[/dim]")
        return True
    try:
        response = context.request.get(pdf_url, timeout=60000)
        if response.status != 200:
            console.print(f"[yellow]PDF HTTP {response.status}: {pdf_url[:60]}...[/yellow]")
            return False
        body = response.body()
        if not body or len(body) < 500:
            console.print(f"[yellow]PDF too small: {pdf_url[:50]}...[/yellow]")
            return False
        os.makedirs(folder, exist_ok=True)
        with open(path, "wb") as f:
            f.write(body)
        console.print(f"[green]  PDF saved: {fname}[/green]")
        return True
    except Exception as e:
        console.print(f"[red]PDF download failed: {e}[/red]")
        return False


def _goto_with_retry(page, url: str) -> bool:
    """
    page.goto with retry on 403 (CloudFront). Random extra wait para di fixed pattern.
    """
    for attempt in range(IRRI_MAX_RETRIES):
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
            status = response.status if response else 0
            if status == 403:
                if attempt < IRRI_MAX_RETRIES - 1:
                    wait = IRRI_RETRY_WAIT + (random.randint(0, IRRI_RANDOM_EXTRA) if IRRI_RANDOM_EXTRA else 0)
                    console.print(f"[yellow]403 Forbidden – waiting {wait}s then retry ({attempt + 1}/{IRRI_MAX_RETRIES})[/yellow]")
                    console.print("[dim]  Tip: IRRI_HEADLESS=false, IRRI_RETRY_WAIT=60, o run mamaya (less traffic)[/dim]")
                    time.sleep(wait)
                    continue
                console.print("[red]403 after retries – skipping. Try IRRI_HEADLESS=false or run later.[/red]")
                return False
            page.wait_for_timeout(2000)
            return True
        except Exception as e:
            err = str(e).lower()
            if "403" in err or "forbidden" in err or attempt < IRRI_MAX_RETRIES - 1:
                wait = IRRI_RETRY_WAIT + (random.randint(0, IRRI_RANDOM_EXTRA) if IRRI_RANDOM_EXTRA else 0)
                console.print(f"[yellow]Request failed: {e} – waiting {wait}s then retry[/yellow]")
                time.sleep(wait)
                continue
            raise
    return False


@require_internet
def run():
    from src.openstat.services.irri import (
        delete_pdf_after_process,
        delete_txt_after_process,
        ingest_pdf_to_corpus,
        ingest_txt_to_corpus,
        open_corpus_for_stream,
        pdf_path_for_url,
        stream_process_enabled,
    )

    console.rule("[bold cyan]IRRI – scrape all news (text + PDFs)")
    headless = os.getenv("IRRI_HEADLESS", "true").lower() != "false"
    if headless:
        console.print("[dim]Browser: headless. Para makita: .env IRRI_HEADLESS=false[/dim]")
    else:
        console.print("[dim]Browser: visible[/dim]")
    console.print("[dim]Kung 403: warm-up + retry. Subukan: IRRI_HEADLESS=false, IRRI_RETRY_WAIT=60, IRRI_DELAY_PAGE=10[/dim]")
    os.makedirs(IRRI_TEXT_DIR, exist_ok=True)
    os.makedirs(IRRI_PDFS_DIR, exist_ok=True)
    existing_filenames = _existing_txt_filenames()

    stream = stream_process_enabled()
    corpus_f = None
    corpus_path = None
    total_stream_records = 0
    if stream:
        parts = ["download -> process -> append corpus"]
        if delete_txt_after_process():
            parts.append("delete .txt")
        if delete_pdf_after_process():
            parts.append("delete PDF")
        console.print(f"[dim]Stream mode: {' -> '.join(parts)}[/dim]")
        corpus_f, corpus_path = open_corpus_for_stream()

    checkpoint = load_checkpoint(CHECKPOINT_PATH, default={"scraped_urls": [], "downloaded_pdf_urls": []})
    done_urls = set(checkpoint.get("scraped_urls", []))
    downloaded_pdfs = set(checkpoint.get("downloaded_pdf_urls", []))

    # Base URLs: reserved only (currently empty); main source = All News listing.
    urls_file = data_path("irri_urls.txt")
    if os.path.isfile(urls_file):
        with open(urls_file, "r", encoding="utf-8") as f:
            extra = [u.strip() for u in f if u.strip() and not u.startswith("#")]
        all_urls = list(dict.fromkeys(IRRI_URLS + extra))
    else:
        all_urls = list(IRRI_URLS)

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    with sync_playwright() as p:
        console.print("[bold]Starting browser...[/bold]")
        if IRRI_USE_CHROMIUM:
            # Bundled Chromium muna – subok kung mas kaunti 403 kaysa Chrome/Edge
            browser = p.chromium.launch(headless=headless, args=launch_args)
            console.print("[dim]Using bundled Chromium (IRRI_USE_CHROMIUM=true)[/dim]")
        else:
            try:
                browser = p.chromium.launch(headless=headless, channel="chrome", args=launch_args)
            except Exception:
                try:
                    browser = p.chromium.launch(headless=headless, channel="msedge", args=launch_args)
                except Exception:
                    browser = p.chromium.launch(headless=True, args=launch_args)

        # Sandali pagkatapos mag-launch bago unang request – "Chromium muna" bago punta sa site
        time.sleep(2)

        # Headers para mukhang normal browser – bawasan 403 from CloudFront
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="en-PH",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.irri.org/",
            },
        )
        page = context.new_page()
        if not apply_page_stealth(page) and not HAS_STEALTH:
            console.print(
                "[dim]playwright-stealth not installed — uv sync --extra openstat[/dim]"
            )

        page.set_default_timeout(30000)

        # Warm-up: unang punta sa homepage para hindi "cold" first request sa news – bawasan 403
        console.print("[dim]Warm-up: loading irri.org homepage first...[/dim]")
        try:
            page.goto("https://www.irri.org/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
        except Exception as e:
            console.print(f"[yellow]Warm-up failed (continuing): {e}[/yellow]")

        # --- News listing: (optional Country+Search) → click card → scrape → balik → next card … → Next page ---
        if _all_news_mode():
            console.print(f"[bold]Listing: {NEWS_LISTING_URL} (All News)[/bold]")
        else:
            console.print(f"[bold]Listing: {NEWS_LISTING_URL} -> Country Philippines -> Search[/bold]")
        if _open_listing_and_apply_search(page):
            page_num = 1
            start_page = _irri_start_page()
            if start_page >= 1:
                # Diretso sa listing page N – para hindi na daanan 1..N-1 (bawasan block)
                if _all_news_mode():
                    start_url = f"{NEWS_LISTING_URL}?page={start_page}"
                else:
                    start_url = f"{NEWS_LISTING_URL}?country=Philippines&page={start_page}"
                console.print(f"[bold]IRRI_START_PAGE={start_page} -> loading [link={start_url}]{start_url}[/link][/bold]")
                if _goto_with_retry(page, start_url):
                    page_num = start_page
                    page.wait_for_timeout(2000)
                else:
                    console.print("[yellow]Start page failed – continuing from page 1[/yellow]")
                    page_num = 1
            while True:
                links_on_page = _get_article_links_on_listing_page(page)
                listing_url = page.url
                console.print(
                    f"[bold]Listing page {page_num}: {len(links_on_page)} cards "
                    f"(save each article immediately, then next page)[/bold]"
                )
                page_fetched: list[str] = []
                page_skipped = 0
                page_failed = 0
                for idx, url in enumerate(links_on_page):
                    url_norm = (url or "").rstrip("/").split("?")[0]
                    if any(u.rstrip("/").split("?")[0] == url_norm for u in done_urls):
                        console.print(f"[dim]  Skip (na-puntahan na): {url[:55]}...[/dim]")
                        page_skipped += 1
                        continue
                    try:
                        console.print(f"[bold]  Card {idx+1}/{len(links_on_page)}[/bold] {url[:60]}...")
                        if not _goto_with_retry(page, url):
                            page_failed += 1
                            continue
                        title = page.title() or ""
                        text = _extract_main_text(page)
                        if not text and title:
                            text = title + "\n\n(No body content extracted)"
                        if not text:
                            text = f"URL: {url}\n(No content extracted)"
                        posted = _parse_article_date(page, text)
                        if not posted:
                            posted = datetime.now().strftime("%Y-%m-%d")
                        base_name = _safe_filename_from_title_and_date(
                            title, posted, url, existing_filenames
                        )
                        txt_path = os.path.join(IRRI_TEXT_DIR, base_name)
                        with open(txt_path, "w", encoding="utf-8") as f:
                            f.write(f"URL: {url}\nTitle: {title}\nDate: {posted}\n\n{text}")
                        console.print(f"[green]  Saved: {base_name}[/green] ({len(text)} chars)")
                        if corpus_f is not None:
                            total_stream_records += ingest_txt_to_corpus(txt_path, corpus_f)
                        page_fetched.append(base_name)
                        pdf_links = _collect_pdf_links(page, url)
                        for j, pdf_url in enumerate(pdf_links):
                            if pdf_url in downloaded_pdfs:
                                continue
                            pdf_path = pdf_path_for_url(pdf_url)
                            if _download_pdf(context, pdf_url, IRRI_PDFS_DIR, len(downloaded_pdfs) + j):
                                downloaded_pdfs.add(pdf_url)
                                if corpus_f is not None and os.path.isfile(pdf_path):
                                    total_stream_records += ingest_pdf_to_corpus(pdf_path, corpus_f)
                            elif corpus_f is not None and os.path.isfile(pdf_path):
                                total_stream_records += ingest_pdf_to_corpus(pdf_path, corpus_f)
                                downloaded_pdfs.add(pdf_url)
                            time.sleep(DELAY_PDF)
                        done_urls.add(url)
                        save_checkpoint(CHECKPOINT_PATH, {
                            "scraped_urls": sorted(done_urls),
                            "downloaded_pdf_urls": sorted(downloaded_pdfs),
                        })
                        # Balik sa listing para iclick yung kasunod na card
                        console.print("[dim]  Balik sa listing...[/dim]")
                        if not _goto_with_retry(page, listing_url):
                            break
                        time.sleep(DELAY_AFTER_PAGE)
                        time.sleep(DELAY_PAGE)
                        if IRRI_RANDOM_EXTRA:
                            extra = random.randint(0, IRRI_RANDOM_EXTRA)
                            time.sleep(extra)
                    except Exception as e:
                        console.print(f"[yellow]  Failed: {e}[/yellow]")
                        page_failed += 1
                        if not _goto_with_retry(page, listing_url):
                            break
                        time.sleep(DELAY_PAGE)
                console.rule(f"[cyan]Page {page_num} summary[/cyan]")
                console.print(
                    f"[bold]Fetched this page:[/bold] {len(page_fetched)} | "
                    f"[dim]Skipped (checkpoint):[/dim] {page_skipped} | "
                    f"[yellow]Failed:[/yellow] {page_failed}"
                )
                for fname in page_fetched:
                    console.print(f"  [green]+[/green] {fname}")
                # Cooldown bawat N pages bago mag-next – bawasan block (hal. page 12 → 13)
                if (
                    IRRI_COOLDOWN_SECONDS > 0
                    and IRRI_COOLDOWN_EVERY_N_PAGES > 0
                    and page_num >= IRRI_COOLDOWN_EVERY_N_PAGES
                    and page_num % IRRI_COOLDOWN_EVERY_N_PAGES == 0
                ):
                    console.print(f"[yellow]Cooldown {IRRI_COOLDOWN_SECONDS}s bago next page (after page {page_num})...[/yellow]")
                    time.sleep(IRRI_COOLDOWN_SECONDS)
                if not _go_to_next_listing_page(page):
                    break
                page_num += 1
                time.sleep(DELAY_PAGE)

        page.close()
        browser.close()

    if corpus_f is not None:
        corpus_f.close()
        console.print(f"[dim]Stream corpus records this run: {total_stream_records} -> {corpus_path}[/dim]")

    console.rule("[bold green]Done")
    console.print(f"Text -> [cyan]{os.path.abspath(IRRI_TEXT_DIR)}[/cyan]")
    console.print(f"PDFs -> [cyan]{os.path.abspath(IRRI_PDFS_DIR)}[/cyan]")
    console.print(f"Scraped: {len(done_urls)} URLs, PDFs downloaded: {len(downloaded_pdfs)}")


if __name__ == "__main__":
    run()
