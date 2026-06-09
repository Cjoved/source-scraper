"""
Pinoy Rice Knowledge Bank (pinoyrice.com) scraper.

TEXT SCRAPING LOGIC:
  - We save page text ONLY from pages that have real article/body content:
      CONTENT_PAGES (home, the-rice-plant, resources, hot-rice, rice-talk),
      PalayCheck subpages, and each Rice Variety .html page.
  - We do NOT save text from listing/catalog pages. DOWNLOADS_PAGES (handouts/*,
      reading-materials/*, poster, books, learning-modules, etc.) are used
      ONLY to collect PDF links; their page text is never written to the corpus.

PDFs: from DOWNLOADS_PAGES (with pagination) + PalayCheck + Rice Varieties → pinoyrice_pdfs/.
Uses Playwright. Checkpoint/resume. After scrape, processing_pinoyrice.run() runs automatically.

Fixes applied (v2):
  [FIX 1] Added handout language variant pages (Tagalog, Cebuano, Iluko, Hiligaynon) to DOWNLOADS_PAGES.
  [FIX 2] Corrected wrong URL paths in DOWNLOADS_PAGES (q-and-a-series, learning-modules, etc.).
  [FIX 3] collect_pdf_links_from_page() now follows pagination links (?&cp=N) to collect ALL handout PDFs.
  [FIX 4] collect_variety_links() now catches root-level .html variety files (e.g. /NSIC-Rc150-Tubigan-9.html).
  [FIX 5] PalayCheck pages now call collect_pdf_links_from_page() so embedded DOWNLOAD links are harvested.
  [FIX 6] headless mode is now env-configurable (HEADLESS=false to show browser, default is headless=True).
"""
from playwright.sync_api import sync_playwright
from src.openstat.utils import require_internet
from src.openstat.config import data_path
from dotenv import load_dotenv
from rich.console import Console
import os
import re
import json
import time
import urllib.parse
from pathlib import Path

from src.openstat.agri_corpus.scraper_utils import normalize_url, load_checkpoint, save_checkpoint
from src.utils.jsonl import append_jsonl

from src.openstat.utils.stealth import apply_page_stealth, stealth_available

HAS_STEALTH = stealth_available()

load_dotenv()
console = Console()

PINOYRICE_BASE = "https://www.pinoyrice.com"
PINOYRICE_JSONL = data_path("pinoyrice_processed", "pinoyrice_corpus.jsonl")
PINOYRICE_PDFS_DIR = data_path("pinoyrice_pdfs")
PINOYRICE_TXT_DIR = data_path("pinoyrice_txt")
CHECKPOINT_PATH = data_path("checkpoints", "pinoyrice_checkpoint.json")

# Pages we SCRAPE FOR TEXT (real article content only). Do not add listing/catalog pages.
CONTENT_PAGES = [
    "https://www.pinoyrice.com/",
    "https://www.pinoyrice.com/the-rice-plant/",
    "https://www.pinoyrice.com/resources/",
    "https://www.pinoyrice.com/hot-rice/",
    "https://www.pinoyrice.com/rice-talk/",
]

# PalayCheck seed page (contains the Seeds/Land/Planting/Nutrient/Water/Pest/Harvest/Postharvest buttons)
PALAYCHECK_SEED_URL = "https://www.pinoyrice.com/palaycheck/variety-and-seed-selection/"

# Rice varieties listing – collect all variety .html and .pdf links from here
RICE_VARIETIES_URL = "https://www.pinoyrice.com/rice-varieties/"

# PDF/LINK COLLECTION ONLY – we do NOT save page text from these (they are listing/catalog pages).
DOWNLOADS_PAGES = [
    "https://www.pinoyrice.com/resources/reading-materials/",
    # Handouts – English + all language variants
    "https://www.pinoyrice.com/handouts/rice-handout-series/",
    "https://www.pinoyrice.com/handouts/tagalog-handouts/",        # [FIX 1] Tagalog
    "https://www.pinoyrice.com/handouts/cebuano-handouts/",        # [FIX 1] Cebuano
    "https://www.pinoyrice.com/handouts/iluko-handouts/",          # [FIX 1] Iluko
    "https://www.pinoyrice.com/handouts/hiligaynon-handouts/",     # [FIX 1] Hiligaynon
    # Other reading material sub-sections
    "https://www.pinoyrice.com/resources/reading-materials/poster/",
    "https://www.pinoyrice.com/resources/reading-materials/books/",
    "https://www.pinoyrice.com/resources/reading-materials/rice-technology-bulletin/",
    "https://www.pinoyrice.com/resources/reading-materials/q-and-a-series/",  # [FIX 2] corrected path
    "https://www.pinoyrice.com/resources/reading-materials/accordion/",
    # Other download sections
    "https://www.pinoyrice.com/resources/learning-modules/",       # [FIX 2] corrected path
    "https://www.pinoyrice.com/resources/technology-videos/",      # [FIX 2] corrected path
    "https://www.pinoyrice.com/resources/audio-clips/",            # [FIX 2] corrected path
    "https://www.pinoyrice.com/rcef-materials/",
]

# [FIX 6] Read headless mode from env. Default True (safe for servers/CI).
# Set HEADLESS=false in your .env or environment to open a visible browser window.
_HEADLESS = os.getenv("HEADLESS", "true").strip().lower() != "false"

DELAY_PAGE = int(os.getenv("PINOYRICE_DELAY_PAGE", "2"))
DELAY_PDF = int(os.getenv("PINOYRICE_DELAY_PDF", "2"))


def _normalize_url(href: str, base: str) -> str | None:
    return normalize_url(href, base)


def _load_checkpoint():
    return load_checkpoint(CHECKPOINT_PATH, default={"scraped_urls": [], "downloaded_urls": []})


def _save_checkpoint(data: dict):
    save_checkpoint(CHECKPOINT_PATH, data)


def _safe_page_filename(url: str) -> str:
    """Use the full URL as basis for filename, stripping symbols invalid for files."""
    safe = re.sub(r"[^\w\-.]", "_", url) or "pinoyrice_page"
    return (safe[:180] + ".txt") if not safe.lower().endswith(".txt") else safe[:180]


def _write_per_file_text(url: str, text: str):
    """Write raw page text to a per-file .txt so we can inspect before cleaning."""
    if not text:
        return
    os.makedirs(PINOYRICE_TXT_DIR, exist_ok=True)
    fname = _safe_page_filename(url)
    path = os.path.join(PINOYRICE_TXT_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# Strip header/footer at extraction so we never save nav/junk to corpus.
_STRIP_FOOTER = (
    "CONTACT US", "PHILRICE TEXT CENTER", "DEPARTMENT OF AGRICULTURE",
    "Are you satisfied with PINOYRICE KNOWLEDGE BANK?", "uQuoted.com",
)
# Menu-like lines: only drop if line is SHORT so we don't drop real content (e.g. "The rice plant is a grass").
_STRIP_LINE_CONTAINS = (
    "HOME", "RICE PRODUCTION", "RICE VARIETIES", "DOWNLOADS", "SEED GROWERS",
    "OFFLINE", "RICE PLANT", "HOT RICE", "RICE TALK", "Search for:", "Menu -HOME",
)
_MENU_LINE_MAX_LEN = 55  # Only drop line if it contains menu phrase AND length <= this (nav items are short)
MIN_CONTENT_LEN = int(os.getenv("PINOYRICE_MIN_CONTENT_LEN", "100"))


def strip_extracted_text(raw: str) -> str:
    """Remove PinoyRice nav/footer from extracted page text. Return cleaned text (may be empty)."""
    if not raw or not raw.strip():
        return ""
    lines = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            continue
        up = s.upper()
        if any(m in up for m in _STRIP_FOOTER):
            break
        # Only drop if line looks like a menu item (short), not real content containing e.g. "rice plant"
        if any(m in up for m in _STRIP_LINE_CONTAINS) and len(s) <= _MENU_LINE_MAX_LEN:
            continue
        if len(s) <= 80 and sum(c.isalpha() for c in s) >= 5 and s == up:
            continue
        lines.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _is_variety_html_url(url: str) -> bool:
    """
    True if this URL points to a standalone variety HTML file.
    These have NO WordPress nav/chrome — just <blockquote> + <table>.
    Covers:
      /wp-content/uploads/rice-varieties/*.html
      /wp-content/uploads/*.html  (e.g. NSIC-Rc396.pdf companion pages)
      root-level *.html           (e.g. /NSIC-Rc150-Tubigan-9.html)
    """
    lower = url.lower()
    if "/wp-content/uploads/" in lower and (lower.endswith(".html") or lower.endswith(".htm")):
        return True
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.lower()
    if (path.endswith(".html") or path.endswith(".htm")) and path.count("/") == 1:
        return True
    return False


# ── JS: standalone variety HTML files ─────────────────────────────────────────
#
# ALL variety files share this exact structure:
#
#   <html><head><title></title></head>    ← <title> is ALWAYS BLANK
#   <body>
#     <blockquote>
#       NSIC Rc466 (Salinas 23)           ← variety name = bare TEXT NODE
#       <br> (sometimes)
#       <table>
#         <tr><td></td><td>Salinas</td></tr>   ← TYPE row: first cell BLANK
#         <tr><td>Average yield:</td><td>3.2 t/ha</td></tr>
#         <tr><td>Maximum yield:</td><td>3.8 t/ha</td></tr>
#         ...
#       </table>
#     </blockquote>
#   </body>
#
# Two bugs to fix:
#   1. Title: <title> tag is blank → must read bare text node via TreeWalker
#   2. Double colon: <td> already contains "Average yield:" → strip trailing ":"
#      before adding ": value"  →  "Average yield: 3.2 t/ha"  (single colon)
#   3. Type row: first <td> is blank → label it "Type:" explicitly
#
_JS_VARIETY = r"""
() => {
    // ── 1. Title from first non-whitespace text node ──────────────────────
    // The <title> tag is blank in ALL variety files.
    // The variety name is a bare text node directly inside <blockquote> or <body>.
    let title = '';
    const walk = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
        {
            acceptNode: function(n) {
                return n.nodeValue.trim().length > 2
                    ? NodeFilter.FILTER_ACCEPT
                    : NodeFilter.FILTER_SKIP;
            }
        }
    );
    if (walk.nextNode()) {
        // Take only the first line (some files have extra whitespace/newlines)
        title = walk.currentNode.nodeValue.trim().split('\n')[0].trim();
    }
    // Ultimate fallback: first <font> or <b> tag text (older variety files)
    if (!title) {
        const fb = document.querySelector('font, b, strong');
        if (fb) title = (fb.innerText || fb.textContent || '').trim();
    }

    // ── 2. Table rows → "Label: Value" lines ─────────────────────────────
    const lines = [];
    if (title) lines.push(title);          // variety name as first line of text

    document.querySelectorAll('table tr').forEach(function(tr) {
        const cells = Array.from(tr.querySelectorAll('td, th'))
            .map(function(c) { return (c.innerText || c.textContent || '').trim(); });

        if (!cells.length) return;

        const raw_label = cells[0] || '';
        const value     = cells[1] || '';

        if (!raw_label && value) {
            // Blank first cell = variety type/environment row (Salinas, Irrigated, etc.)
            lines.push('Type: ' + value);
        } else if (raw_label && value) {
            // Strip trailing colon from label to avoid "Average yield:: 3.2 t/ha"
            const label = raw_label.replace(/:+$/, '').trim();
            lines.push(label + ': ' + value);
        } else if (raw_label) {
            lines.push(raw_label);
        }
    });

    return JSON.stringify({ title: title, text: lines.join('\n') });
}
"""

# ── JS: full WordPress pages (PalayCheck, home, rice-talk, etc.) ──────────────
_JS_WP = r"""
() => {
    const SELECTORS = [
        'main', 'article', '.content', '#content',
        '.entry-content', '.post-content', 'body'
    ];
    let container = null;
    for (const sel of SELECTORS) {
        const el = document.querySelector(sel);
        if (el && (el.innerText || '').trim().length > 50) {
            container = el; break;
        }
    }
    if (!container) return '';

    const clone = container.cloneNode(true);

    // Remove structural chrome
    ['nav', 'header', 'footer', 'script', 'style', 'noscript'].forEach(function(tag) {
        clone.querySelectorAll(tag).forEach(function(el) { el.remove(); });
    });

    // Remove image-only <a> links (PalayCheck icon nav: Seeds / Land / Planting …)
    clone.querySelectorAll('a').forEach(function(a) {
        const txt = (a.innerText || a.textContent || '').trim();
        if (a.querySelector('img') && txt.length < 4) a.remove();
    });

    // Remove "More X >>" navigation links
    clone.querySelectorAll('a').forEach(function(a) {
        const t = (a.innerText || a.textContent || '').trim();
        if (/^More\s+.{1,50}(>>|»)\s*$/i.test(t)) a.remove();
    });

    // Cut MATERIALS heading and everything after (handout/video listing junk)
    const headings = Array.from(clone.querySelectorAll('h2, h3'));
    for (let i = 0; i < headings.length; i++) {
        const h = headings[i];
        if ((h.innerText || h.textContent || '').trim().toUpperCase() === 'MATERIALS') {
            let node = h;
            while (node) {
                const next = node.nextSibling;
                if (node.parentNode) node.parentNode.removeChild(node);
                node = next;
            }
            break;
        }
    }

    // Extract only meaningful tags
    const parts = [];
    clone.querySelectorAll('h1, h2, h3, p, li, td, th').forEach(function(el) {
        const parent = el.parentElement;
        if (parent && (parent.tagName === 'LI' ||
                       parent.tagName === 'TD' ||
                       parent.tagName === 'TH')) return;
        const t = (el.innerText || el.textContent || '').trim();
        if (t.length > 8) parts.push(t);
    });

    const structured = parts.join('\n').trim();
    if (structured.length >= 80) return structured;

    return (clone.innerText || clone.textContent || '').trim();
}
"""


def extract_page_text(page, url: str = "") -> tuple[str, str]:
    """
    Extract clean title + text from a Playwright page.

    PATH A — Standalone variety HTML (/wp-content/uploads/*.html, root *.html):
      Uses _JS_VARIETY:
        • Title  → first non-whitespace TEXT NODE (bare text inside <blockquote>)
                   because <title> tag is always blank in variety files
        • Type   → blank-first-cell table row gets labelled "Type: Salinas" etc.
        • Fields → trailing ":" stripped from label cells → single colon output

    PATH B — Full WordPress pages (PalayCheck, home, rice-talk, etc.):
      Uses _JS_WP: DOM surgery (removes nav/icon-row/MATERIALS) then extracts
      h1/h2/h3/p/li/td/th only.

    Falls back to plain innerText() if JS fails on either path.
    Returns (title, text).
    """
    if _is_variety_html_url(url):
        # ── Path A: standalone variety HTML ──────────────────────────────
        try:
            raw = page.evaluate(_JS_VARIETY)
            data = json.loads(raw or "{}")
            title = data.get("title", "").strip()
            text  = data.get("text",  "").strip()
            return title, text
        except Exception as e:
            console.print(f"[yellow]extract_page_text (variety JS) failed: {e} — using innerText[/yellow]")
            try:
                body  = page.locator("body").inner_text().strip()
                title = body.split("\n")[0].strip() if body else ""
                return title, body
            except Exception:
                return "", ""
    else:
        # ── Path B: full WordPress page ───────────────────────────────────
        try:
            title = page.title() or ""
        except Exception:
            title = ""
        try:
            text = (page.evaluate(_JS_WP) or "").strip()
        except Exception as e:
            console.print(f"[yellow]extract_page_text (WP JS) failed: {e} — using innerText[/yellow]")
            text = ""
            for sel in ["main", "article", ".content", "#content",
                        ".entry-content", ".post-content", "body"]:
                try:
                    loc = page.locator(sel).first
                    if loc.count() > 0:
                        raw = loc.inner_text()
                        if raw and len(raw.strip()) > 50:
                            text = raw.strip()
                            break
                except Exception:
                    continue
        return title, text


def collect_pdf_links_from_page(page, page_url: str) -> list[str]:
    """
    From any page, get all same-domain PDF links (direct .pdf and wpdmdl=).
    For use on Downloads pages (Reading Materials, Handouts, Books, etc.).

    [FIX 3] Now follows pagination links (?&cp=N) so all paginated handout pages
    are traversed and every DOWNLOAD/VIEW link is captured.
    """
    out = []
    seen_pdfs: set[str] = set()
    visited_pages: set[str] = set()

    def _scrape_current_page(current_url: str):
        """Collect PDF links from the current loaded page."""
        try:
            for a in page.locator("a[href]").all():
                href = a.get_attribute("href")
                if not href or not href.strip():
                    continue
                full = _normalize_url(href, current_url)
                if not full or full in seen_pdfs:
                    continue
                if "pinoyrice.com" not in full:
                    continue
                lower = full.lower()
                if ".pdf" in lower or "wpdmdl=" in full:
                    seen_pdfs.add(full)
                    out.append(full)
        except Exception as e:
            console.print(f"[yellow]collect_pdf_links_from_page (scrape): {e}[/yellow]")

    def _find_next_page_urls(current_url: str) -> list[str]:
        """
        Find all pagination links on the current page (?&cp=N or ?cp=N).
        Returns absolute URLs not yet visited.
        """
        next_urls = []
        try:
            for a in page.locator("a[href]").all():
                href = a.get_attribute("href")
                if not href:
                    continue
                # Pagination links use ?&cp=N or ?cp=N
                if "cp=" not in href:
                    continue
                full = _normalize_url(href, current_url)
                if not full or full in visited_pages:
                    continue
                if "pinoyrice.com" not in full:
                    continue
                next_urls.append(full)
        except Exception as e:
            console.print(f"[yellow]collect_pdf_links_from_page (pagination): {e}[/yellow]")
        return next_urls

    # Scrape the already-loaded first page
    visited_pages.add(page_url)
    _scrape_current_page(page_url)

    # Follow all pagination links until exhausted
    pages_to_visit = _find_next_page_urls(page_url)
    while pages_to_visit:
        next_url = pages_to_visit.pop(0)
        if next_url in visited_pages:
            continue
        visited_pages.add(next_url)
        try:
            console.print(f"[dim]  Pagination: {next_url}[/dim]")
            page.goto(next_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1500)
        except Exception as e:
            console.print(f"[yellow]  Pagination load failed {next_url}: {e}[/yellow]")
            continue
        _scrape_current_page(next_url)
        # Discover further pages from this page too
        for further in _find_next_page_urls(next_url):
            if further not in visited_pages:
                pages_to_visit.append(further)
        time.sleep(DELAY_PAGE)

    if len(visited_pages) > 1:
        console.print(f"[dim]  Followed {len(visited_pages)} paginated pages, found {len(out)} PDF links[/dim]")

    return out


def collect_variety_links(page, page_url: str) -> tuple[list[str], list[str]]:
    """
    From rice-varieties page (or any page), get all links to variety HTML and PDF.
    Returns (html_urls, pdf_urls). Also handles same-domain links to uploads/rice-varieties and wpdmdl.

    [FIX 4] Also catches root-level .html variety pages (e.g. /NSIC-Rc150-Tubigan-9.html)
    that are not under /wp-content/uploads/ or /rice-varieties/ paths.
    """
    html_urls = []
    pdf_urls = []
    seen = set()
    try:
        for a in page.locator("a[href]").all():
            href = a.get_attribute("href")
            if not href:
                continue
            full = _normalize_url(href, page_url)
            if not full or full in seen:
                continue
            if "pinoyrice.com" not in full:
                continue
            seen.add(full)
            lower = full.lower()

            # --- PDF links ---
            if ".pdf" in lower and ("uploads" in lower or "wpdmdl" in lower or "pinoyrice" in full):
                pdf_urls.append(full)
            elif "wpdmdl=" in full:
                pdf_urls.append(full)  # will resolve later

            # --- HTML variety links ---
            # Original: under /wp-content/uploads/rice-varieties/
            elif "rice-varieties" in lower and (".html" in lower or ".htm" in lower):
                html_urls.append(full)
            # Original: other paths under /wp-content/uploads/
            elif "/wp-content/uploads/" in full and (".html" in lower or ".htm" in lower):
                html_urls.append(full)
            # [FIX 4] Root-level variety pages, e.g. /NSIC-Rc150-Tubigan-9.html
            else:
                parsed = urllib.parse.urlparse(full)
                path_lower = parsed.path.lower()
                # Must be a direct HTML file at root or one level deep (not a known section)
                if (path_lower.endswith(".html") or path_lower.endswith(".htm")):
                    # Exclude known non-variety section paths
                    skip_prefixes = (
                        "/palaycheck/", "/resources/", "/handouts/",
                        "/wp-content/", "/rice-talk", "/hot-rice",
                        "/the-rice-plant", "/offline", "/inbred-rice",
                    )
                    if not any(parsed.path.startswith(p) for p in skip_prefixes):
                        html_urls.append(full)

    except Exception as e:
        console.print(f"[yellow]collect_variety_links: {e}[/yellow]")
    return html_urls, pdf_urls


def follow_wpdmdl_get_pdf_url(page, url: str) -> str | None:
    """Visit ?wpdmdl=... and return final PDF URL if it redirects to PDF."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)
        if page.url and ".pdf" in page.url.lower():
            return page.url
        for a in page.locator("a[href*='.pdf']").all():
            h = a.get_attribute("href")
            if h:
                return _normalize_url(h, page.url)
    except Exception:
        pass
    return None


def _safe_pdf_name(url: str, index: int) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        name = (parsed.path or "").split("/")[-1] or f"pinoyrice_{index}"
    except Exception:
        name = f"pinoyrice_{index}"
    name = re.sub(r"[^\w\-.]", "_", name)
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name[:180]


def download_pdf(context, pdf_url: str, folder: str, index: int, retries: int = 2) -> bool:
    """
    Download one PDF with basic retry logic.
    Retries help for transient errors like 'socket hang up'.
    """
    filename = _safe_pdf_name(pdf_url, index)
    path = os.path.join(folder, filename)
    if os.path.isfile(path):
        console.print(f"[dim]  Skip PDF (exists): {filename}[/dim]")
        return True
    attempt = 0
    while attempt <= retries:
        try:
            response = context.request.get(pdf_url, timeout=120000)
            if response.status != 200:
                console.print(f"[yellow]PDF HTTP {response.status} for {pdf_url}[/yellow]")
                return False
            body = response.body()
            if not body or len(body) < 100:
                console.print(f"[yellow]PDF too small or empty: {pdf_url}[/yellow]")
                return False
            os.makedirs(folder, exist_ok=True)
            with open(path, "wb") as f:
                f.write(body)
            console.print(f"[green]  Saved PDF: {filename}[/green]")
            return True
        except Exception as e:
            attempt += 1
            console.print(f"[red]PDF download failed (attempt {attempt}/{retries + 1}) for {pdf_url}: {e}[/red]")
            if attempt > retries:
                return False
            time.sleep(DELAY_PDF)


def process_pdf_urls(page, context, pdf_urls: list[str], downloaded: set[str], start_index: int) -> int:
    """
    Resolve and download PDF URLs immediately for the current page, instead of
    queueing a huge global list. Returns next free index for filenames.
    """
    idx = start_index
    for url in pdf_urls:
        if not url:
            continue
        if url in downloaded:
            console.print(f"[dim]  Skip PDF (already downloaded): {url}[/dim]")
            continue
        final_url = url
        if "wpdmdl=" in url:
            resolved = follow_wpdmdl_get_pdf_url(page, url)
            if not resolved:
                continue
            final_url = resolved
        if download_pdf(context, final_url, PINOYRICE_PDFS_DIR, idx):
            downloaded.add(url)
            downloaded.add(final_url)
            idx += 1
        time.sleep(DELAY_PDF)
    return idx


def _doc_id(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        path = (parsed.path or "").strip("/")
        return re.sub(r"[^\w\-.]", "_", path)[:120] or "pinoyrice_page"
    except Exception:
        return "pinoyrice_page"


@require_internet
def run():
    console.rule("[bold cyan]Pinoy Rice Knowledge Bank Scraper")
    os.makedirs(PINOYRICE_PDFS_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(PINOYRICE_JSONL), exist_ok=True)

    console.print(f"[dim]Headless mode: {_HEADLESS} (set HEADLESS=false to show browser)[/dim]")

    checkpoint = _load_checkpoint()
    scraped = set(checkpoint.get("scraped_urls", []))
    downloaded = set(checkpoint.get("downloaded_urls", []))
    pdf_index = len(downloaded)

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
    ]

    # [FIX 6] Use env-configurable headless mode instead of always headless=False
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=_HEADLESS, channel="chrome", args=launch_args)
        except Exception:
            try:
                browser = p.chromium.launch(headless=_HEADLESS, channel="msedge", args=launch_args)
            except Exception:
                browser = p.chromium.launch(headless=_HEADLESS, args=launch_args)

        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="en-PH",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        page = context.new_page()
        if apply_page_stealth(page):
            console.print("[dim]Stealth evasions applied.[/dim]")

        page.set_default_timeout(30000)

        # ---- 1) Scrape main content pages ----
        for url in CONTENT_PAGES:
            if url in scraped:
                console.print(f"[dim]Skip (done): {url}[/dim]")
                continue
            try:
                console.print(f"[bold]Content: {url}[/bold]")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                title, raw_text = extract_page_text(page, url)
                text = strip_extracted_text(raw_text or "")
                if text and len(text) >= MIN_CONTENT_LEN:
                    record = {
                        "text": text,
                        "input": text,
                        "content": text,
                        "source": "pinoyrice",
                        "url": url,
                        "title": title,
                        "doc_id": _doc_id(url),
                    }
                    append_jsonl(record, PINOYRICE_JSONL)
                    _write_per_file_text(url, raw_text)
                    scraped.add(url)
                    console.print(f"[green]  Text: {len(text)} chars[/green]")
                else:
                    console.print("[yellow]  No/short content after strip.[/yellow]")
                    scraped.add(url)
            except Exception as e:
                console.print(f"[yellow]Failed {url}: {e}[/yellow]")
            time.sleep(DELAY_PAGE)

        # ---- 2) PalayCheck pages (Seeds/Land/Planting/Nutrient/Water/Pest/Harvest/Postharvest) ----
        palay_urls = set()
        console.print(f"[bold]PalayCheck seed page: {PALAYCHECK_SEED_URL}[/bold]")
        try:
            page.goto(PALAYCHECK_SEED_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
        except Exception as e:
            console.print(f"[yellow]Could not load PalayCheck seed page: {e}[/yellow]")
        else:
            # always include the main PalayCheck seed URL
            palay_urls.add(PALAYCHECK_SEED_URL)
            try:
                for a in page.locator("a[href]").all():
                    href = a.get_attribute("href")
                    if not href:
                        continue
                    full = _normalize_url(href, PALAYCHECK_SEED_URL)
                    if not full:
                        continue
                    if "pinoyrice.com" not in full or "/palaycheck/" not in full:
                        continue
                    # drop fragment so /foo#bar and /foo#baz are treated as one
                    full = full.split("#", 1)[0]
                    palay_urls.add(full)
            except Exception as e:
                console.print(f"[yellow]collect PalayCheck links: {e}[/yellow]")
            console.print(f"[dim]  PalayCheck URLs: {len(palay_urls)}[/dim]")

            for url in sorted(palay_urls):
                if url in scraped:
                    console.print(f"[dim]Skip (done): {url}[/dim]")
                    # Still collect PalayCheck PDFs even if text was already scraped
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(2000)
                        pdfs = collect_pdf_links_from_page(page, url)
                        if pdfs:
                            console.print(f"[dim]  PalayCheck PDF links (rescrape): {len(pdfs)}[/dim]")
                            pdf_index = process_pdf_urls(page, context, pdfs, downloaded, pdf_index)
                    except Exception:
                        pass
                    continue
                try:
                    console.print(f"[bold]PalayCheck: {url}[/bold]")
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2000)
                    title, raw_text = extract_page_text(page, url)
                    text = strip_extracted_text(raw_text or "")
                    if text and len(text) >= MIN_CONTENT_LEN:
                        record = {
                            "text": text,
                            "input": text,
                            "content": text,
                            "source": "pinoyrice",
                            "url": url,
                            "title": title,
                            "doc_id": _doc_id(url),
                        }
                        append_jsonl(record, PINOYRICE_JSONL)
                        _write_per_file_text(url, raw_text)
                        scraped.add(url)
                        console.print(f"[green]  Text: {len(text)} chars[/green]")
                    else:
                        scraped.add(url)
                        console.print("[yellow]  No/short content after strip.[/yellow]")
                    # [FIX 5] Collect embedded DOWNLOAD/VIEW PDF links from each PalayCheck page
                    pdfs = collect_pdf_links_from_page(page, url)
                    if pdfs:
                        console.print(f"[dim]  PalayCheck PDF links: {len(pdfs)}[/dim]")
                        pdf_index = process_pdf_urls(page, context, pdfs, downloaded, pdf_index)
                except Exception as e:
                    console.print(f"[yellow]Failed {url}: {e}[/yellow]")
                    pdfs = []
                time.sleep(DELAY_PAGE)
        # ---- 3) Downloads section: PDF link collection ONLY (no text; these are listing pages) ----
        for url in DOWNLOADS_PAGES:
            if url in scraped:
                console.print(f"[dim]Skip (done): {url}[/dim]")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(1500)
                    pdfs = collect_pdf_links_from_page(page, url)
                    if pdfs:
                        console.print(f"[dim]  PDF links: {len(pdfs)}[/dim]")
                        pdf_index = process_pdf_urls(page, context, pdfs, downloaded, pdf_index)
                except Exception:
                    pass
                continue
            try:
                console.print(f"[bold]Downloads (PDFs only): {url}[/bold]")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                scraped.add(url)
                pdfs = collect_pdf_links_from_page(page, url)
                if pdfs:
                    console.print(f"[green]  PDF links: {len(pdfs)}[/green]")
                    pdf_index = process_pdf_urls(page, context, pdfs, downloaded, pdf_index)
                else:
                    console.print("[dim]  No PDF links.[/dim]")
            except Exception as e:
                console.print(f"[yellow]Failed {url}: {e}[/yellow]")
            time.sleep(DELAY_PAGE)

        # ---- 4) Rice Varieties: collect links ----
        console.print(f"[bold]Varieties: {RICE_VARIETIES_URL}[/bold]")
        try:
            page.goto(RICE_VARIETIES_URL, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
        except Exception as e:
            console.print(f"[yellow]Could not load varieties page: {e}[/yellow]")
        else:
            # [FIX 4] collect_variety_links now also catches root-level .html variety pages
            html_links, pdf_links = collect_variety_links(page, RICE_VARIETIES_URL)
            console.print(f"[dim]  HTML: {len(html_links)}, PDF: {len(pdf_links)}[/dim]")
            if pdf_links:
                pdf_index = process_pdf_urls(page, context, pdf_links, downloaded, pdf_index)

            # ---- 5) Scrape each variety HTML ----
            for url in html_links:
                if url in scraped:
                    continue
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(1500)
                    title, raw_text = extract_page_text(page, url)
                    text = strip_extracted_text(raw_text or "")
                    if text and len(text) >= MIN_CONTENT_LEN:
                        record = {
                            "text": text,
                            "input": text,
                            "content": text,
                            "source": "pinoyrice",
                            "url": url,
                            "title": title,
                            "doc_id": _doc_id(url),
                        }
                        append_jsonl(record, PINOYRICE_JSONL)
                        _write_per_file_text(url, raw_text)
                        scraped.add(url)
                except Exception:
                    pass
                time.sleep(DELAY_PAGE)

        checkpoint["scraped_urls"] = sorted(scraped)
        checkpoint["downloaded_urls"] = sorted(downloaded)
        _save_checkpoint(checkpoint)

        page.close()
        browser.close()

    console.rule("[bold green]Scrape done")
    console.print(f"Text → [cyan]{PINOYRICE_JSONL}[/cyan]")
    console.print(f"PDFs → [cyan]{os.path.abspath(PINOYRICE_PDFS_DIR)}[/cyan]")
    console.print(f"Scraped pages: {len(scraped)}, Downloaded PDFs: {len(downloaded)}")

if __name__ == "__main__":
    run()