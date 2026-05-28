"""
PhilRice News scraper – bawat article: text mula title hanggang (kasama) ang
"HOW DOES THIS POST MAKE YOU FEEL?" at mga percentage. Filename = philrice_news_MM-DD-YY.txt (posted date).
"""
from playwright.sync_api import sync_playwright
from src.openstat.utils import require_internet
from src.openstat.config import data_path
from dotenv import load_dotenv
from rich.console import Console
from datetime import datetime
import os
import re
import json
import time

try:
    from playwright_stealth import stealth_sync
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

load_dotenv()
console = Console()

PHILRICE_NEWS_URL = "https://www.philrice.gov.ph/news/"
PHILRICE_NEWS_DIR = data_path("philrice_news")
CHECKPOINT_PATH = data_path("checkpoints", "philrice_news_checkpoint.json")

DELAY_PAGE = int(os.getenv("PHILRICE_NEWS_DELAY", "3"))

_MONTH = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
    "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


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


def _safe_filename_from_date(posted_mm_dd_yy: str, same_day_index: int) -> str:
    """e.g. philrice_news_03-11-26.txt o philrice_news_03-11-26_2.txt"""
    base = f"philrice_news_{posted_mm_dd_yy}"
    if same_day_index > 1:
        base += f"_{same_day_index}"
    return base + ".txt"


def _load_checkpoint() -> set:
    if not os.path.isfile(CHECKPOINT_PATH):
        return set()
    try:
        with open(CHECKPOINT_PATH, "r", encoding="utf-8") as f:
            return set(json.load(f).get("scraped_urls", []))
    except Exception:
        return set()


def _save_checkpoint(scraped_urls: list):
    try:
        os.makedirs(os.path.dirname(CHECKPOINT_PATH), exist_ok=True)
        with open(CHECKPOINT_PATH, "w", encoding="utf-8") as f:
            json.dump({"scraped_urls": scraped_urls, "updated": datetime.now().isoformat()}, f, indent=2)
    except Exception as e:
        console.print(f"[dim]Checkpoint save: {e}[/dim]")


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
def run():
    console.rule("[bold cyan]PhilRice News – title hanggang HOW DOES THIS POST MAKE YOU FEEL + %")
    os.makedirs(PHILRICE_NEWS_DIR, exist_ok=True)
    scraped = list(_load_checkpoint())
    date_count = {}  # MM-DD-YY -> count para same-day _2, _3

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
        if HAS_STEALTH:
            try:
                page = context.new_page()
                stealth_sync(page)
            except Exception:
                page = context.new_page()
        else:
            page = context.new_page()

        page.set_default_timeout(30000)

        try:
            console.print(f"[bold]Listing: {PHILRICE_NEWS_URL}[/bold]")
            page.goto(PHILRICE_NEWS_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)
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

            to_scrape = [(t, u) for t, u in all_entries if u not in scraped]
            console.print(f"[bold]Articles to scrape: {len(to_scrape)}[/bold]")

            for title_text, url in to_scrape:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2000)
                    posted = _parse_posted_date(page)
                    if not posted:
                        posted = datetime.now().strftime("%m-%d-%y")
                    date_count[posted] = date_count.get(posted, 0) + 1
                    same_day = date_count[posted]
                    fname = _safe_filename_from_date(posted, same_day)
                    out_path = os.path.join(PHILRICE_NEWS_DIR, fname)
                    body = _extract_article_text_to_feel_section(page)
                    if not body:
                        body = title_text + "\n\n(Content not extracted)"
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(body)
                    console.print(f"[green]  {fname}[/green]")
                    scraped.append(url)
                except Exception as e:
                    console.print(f"[yellow]  Skip {url[:50]}...: {e}[/yellow]")
                time.sleep(DELAY_PAGE)

            _save_checkpoint(scraped)

        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            _save_checkpoint(scraped)
        finally:
            page.close()
            browser.close()

    # (per-article files in PHILRICE_NEWS_DIR) – isang linya bawat headline (yung “button” text lang)
    console.rule("[bold green]Done")
    console.print(f"Output → [cyan]{os.path.abspath(PHILRICE_NEWS_DIR)}[/cyan]")
    console.print(f"Files: philrice_news_MM-DD-YY.txt (title → HOW DOES THIS POST MAKE YOU FEEL + %)")
    console.print(f"Scraped: [bold]{len(scraped)}[/bold] articles")


if __name__ == "__main__":
    run()
