"""
PhilRice PDF scraper – collects PDFs from PhilRice downloads and knowledge products.
Uses Playwright (same stack as OpenSTAT scraper). Checkpoint/resume supported.
"""
from playwright.sync_api import sync_playwright
from src.openstat.utils import wait_for_selector_with_retry, require_internet
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

from src.openstat.utils.stealth import apply_page_stealth, stealth_available

HAS_STEALTH = stealth_available()

load_dotenv()
console = Console()

PHILRICE_PDFS_DIR = data_path("philrice_pdfs")
CHECKPOINT_PATH = data_path("checkpoints", "philrice_checkpoint.json")

# PhilRice: main pages at sub-pages na may listahan ng PDF (kailangan puntahan/click-through)
PHILRICE_BASE_URLS = [
    "https://www.philrice.gov.ph/downloads/",
    "https://www.philrice.gov.ph/products/knowledge-products/",
]
# Sub-pages na siguradong may agri PDF – puntahan after main page (parang “pinindot” ang section)
# Covers all major PDF sections per PhilRice Downloads: R&D Highlights, Magazine, RS4DM, References, Milestones (Annual Reports).
PHILRICE_SUB_PAGES = [
    "https://www.philrice.gov.ph/databases/rd-highlights/",  # R&D Highlights (taon links → PDF)
    "https://www.philrice.gov.ph/e-magazine/",  # PhilRice Magazine – Read/Download + pagination
    "https://www.philrice.gov.ph/databases/rice-science-for-decision-makers/",  # RS4DM – Read/Download + pagination
    "https://www.philrice.gov.ph/databases/references/",  # References – same layout: Read/Download + pagination
    "https://www.philrice.gov.ph/databases/milestones/",  # Annual Reports / Milestones (2013–2020 PDFs)
]

# Delay between requests (seconds) – be nice to the server
def _delay(s: str, default: int) -> int:
    v = os.getenv(s, str(default)).strip()
    try:
        return max(1, int(v)) if v else default
    except ValueError:
        return default
# Balanced: hindi masyadong mabilis (iwas timeout sa mahina signal), hindi 1 min (sobrang tagal)
DELAY_PAGE = _delay("PHILRICE_DELAY_PAGE", 8)
DELAY_PDF = _delay("PHILRICE_DELAY_PDF", 5)

# Downloads lang: true = kunin lang PDF mula sa Downloads page + mga sub-button under Publications (PhilRice Magazine, R&D Highlights, Rice Science, References, More Information Materials). Hindi kasama Forms, Style Guide, Stories, Videos.
DOWNLOADS_ONLY = os.getenv("PHILRICE_DOWNLOADS_ONLY", "true").strip().lower() in ("true", "1", "yes")

# Sub-buttons under Publications lang (yung list sa Downloads) – hindi Forms, Journal guidelines, Stories, Videos
PUBLICATION_SUB_KEYWORDS = [
    "magazine", "rd-highlights", "r-d-highlights", "rice-science", "decision", "references",
    "information-materials", "highlights",
]

# Skip disabled: kunin lahat ng PDF (walang blocklist).
def _should_skip_pdf(url: str) -> bool:
    """Lagi False – lahat ng PDF kinukuha na."""
    return False


def _load_checkpoint():
    """Load set of completed PDF URLs (download + process in stream mode)."""
    data = load_checkpoint(CHECKPOINT_PATH, default={"completed_urls": [], "downloaded_urls": []})
    completed = data.get("completed_urls") or data.get("downloaded_urls") or []
    return set(completed)


def _save_checkpoint(completed_urls: set[str]) -> None:
    """Save checkpoint; keep downloaded_urls alias for older tooling."""
    urls = sorted(completed_urls)
    save_checkpoint(
        CHECKPOINT_PATH,
        {"completed_urls": urls, "downloaded_urls": urls},
    )


def _is_pdf_link(href: str) -> bool:
    if not href or not href.strip():
        return False
    href = href.strip().lower()
    if href.endswith(".pdf"):
        return True
    if ".pdf?" in href or ".pdf#" in href:
        return True
    return False


def _normalize_url(url: str, base: str) -> str:
    """Make absolute URL."""
    return normalize_url(url, base) or ""


def _safe_filename(url: str, index: int) -> str:
    """Generate a safe filename from URL or index."""
    try:
        parsed = urllib.parse.urlparse(url)
        path = parsed.path or ""
        name = path.split("/")[-1] or f"philrice_{index}"
    except Exception:
        name = f"philrice_{index}"
    name = re.sub(r"[^\w\-_.]", "_", name)
    if not name.lower().endswith(".pdf"):
        name = name + ".pdf"
    return name[:200]


def _is_pdf_or_download_url(url: str) -> bool:
    """True kung mukhang PDF o download-manager link (wpdmdl o typo wpdml). Huwag nav (/downloads/, /home, forms)."""
    if not url:
        return False
    u = url.lower()
    if "/downloads" in u and u.rstrip("/").endswith("downloads"):
        return False
    if u.endswith("/home") or "docs.google.com/forms" in u:
        return False
    if ".pdf" in u:
        return True
    if "wpdmdl=" in u or "wpdml=" in u:  # wpdml = typo sa ilang RS4DM links
        return True
    return False


def collect_pdf_links_from_page(page, page_url: str) -> list[str]:
    """
    Get all PDF links from current page. Lahat ng pages (e-magazine, rd-highlights, RS4DM, references):
    - Read = direct .pdf, class fancybox-pdf.
    - Download = direct .pdf o ?wpdmdl= / ?wpdml=.
    - rd-highlights: Branch/Division (Isabela, Batac, ...) = direct .pdf, fancybox-pdf.
    """
    out = []
    try:
        # Primary: fancybox-pdf (Read + rd-highlights Branch/Division) at a[download] (Download buttons)
        for a in page.locator("a.fancybox-pdf[href], a[href][download]").all():
            href = a.get_attribute("href")
            if not href or not href.strip():
                continue
            full = _normalize_url(href, page_url)
            if not full or full in out:
                continue
            if not _is_pdf_or_download_url(full):
                continue
            out.append(full)
        # Fallback: a[href] na .pdf o text Read/Download (na talagang PDF o wpdmdl)
        links = page.query_selector_all("a[href]")
        for a in links:
            href = a.get_attribute("href")
            if not href or not href.strip():
                continue
            full = _normalize_url(href, page_url)
            if not full or full in out:
                continue
            if _is_pdf_link(href):
                out.append(full)
                continue
            text = (a.inner_text() or "").strip().lower()
            if text == "read" and ".pdf" in full.lower():
                out.append(full)
                continue
            if text == "download" and _is_pdf_or_download_url(full):
                out.append(full)
    except Exception as e:
        console.print(f"[yellow]Error collecting links: {e}[/yellow]")
    return out


def collect_internal_section_links(page, page_url: str) -> list[str]:
    """
    Get links na parang "section" (same domain, hindi PDF, hindi #) – para puntahan
    at doon mangolekta ng PDF (parang pinindot ang button/section).
    """
    out = []
    try:
        base_domain = "philrice.gov.ph"
        links = page.query_selector_all("a[href]")
        for a in links:
            href = a.get_attribute("href")
            if not href or href.strip().startswith("#") or "mailto:" in href:
                continue
            full = _normalize_url(href, page_url)
            if not full or full in out:
                continue
            if base_domain not in full:
                continue
            if _is_pdf_link(href):
                continue
            # Iwasan ang labas na link, home lang, o repeat
            path = urllib.parse.urlparse(full).path or ""
            if path.strip("/") in ("", "downloads", "products", "databases"):
                continue
            out.append(full)
    except Exception:
        pass
    return out


def _current_page_number(url: str) -> int:
    """Kunin page number mula sa URL, e.g. /e-magazine/page/3/ -> 3, /e-magazine/ -> 1."""
    if not url:
        return 1
    m = re.search(r"/page/(\d+)/?", url)
    return int(m.group(1)) if m else 1


def go_to_next_pagination_page(page, current_url: str) -> bool:
    """
    I-click ang "Next" / ">>" o ang link na next page number (huwag i-click ang "1" o previous).
    Kung i-click natin basta anumang page link, puwede tayong pumunta pabalik sa page 1.
    """
    try:
        current_page = _current_page_number(current_url)
        # Una: hanapin ">>" (next) o "Next" – huwag "Last >>"
        for loc in [
            page.locator("a:has-text('Next')").first,
            page.locator(".pagination a").filter(has_not_text="Last").filter(has_text=">>").first,
            page.locator("a").filter(has_text=">>").filter(has_not_text="Last").first,
        ]:
            if loc.count() > 0:
                href = loc.get_attribute("href")
                if href and "#" not in (href or ""):
                    loc.click()
                    page.wait_for_timeout(5000)
                    if page.url != current_url:
                        console.print(f"[dim]  → Next page: {page.url}[/dim]")
                        return True
                    return False
        # Fallback: i-click lang ang link na may page number = current_page + 1 (huwag pabalik sa 1,2,...)
        # Fallback na generic selector (rarely used na ngayon)
        next_links = page.locator("a[href*='page'], a[href*='pagina']")
        for i in range(next_links.count()):
            a = next_links.nth(i)
            h = a.get_attribute("href")
            if not h or "#" in h:
                continue
            a.click()
            page.wait_for_timeout(5000)
            if page.url != current_url:
                console.print(f"[dim]  → Next page (fallback): {page.url[:70]}...[/dim]")
                return True
            return False
    except Exception:
        pass
    return False


def click_section_then_collect(page, page_url: str, section_text_pattern: str) -> list[str]:
    """
    Hanapin link/button na may text (e.g. "R&D Highlights") → click → wait → collect PDF links.
    """
    pdfs = []
    try:
        loc = page.locator(f"a:has-text('{section_text_pattern}')")
        if loc.count() > 0:
            loc.first.click()
            page.wait_for_timeout(5000)
            pdfs = collect_pdf_links_from_page(page, page_url)
    except Exception:
        pass
    return pdfs


# Taon sa "Previous R and D highlights" (2023, 2022, ... 2008-2011) – link text o section list
RD_HIGHLIGHTS_YEAR_PATTERN = re.compile(r"^(20\d{2}|2008-2011)$")


def collect_rd_highlights_previous_year_links(page, page_url: str) -> list[str]:
    """
    Kunin lahat ng href ng links sa "Previous R and D highlights" (taon: 2023, 2022, ... 2008-2011).
    Pag pinindot yan, kusang may lalabas na PDF – so we need to follow each and get the PDF URL.
    """
    urls = []
    try:
        for a in page.locator("a[href]").all():
            text = (a.inner_text() or "").strip()
            if RD_HIGHLIGHTS_YEAR_PATTERN.match(text):
                href = a.get_attribute("href")
                if href:
                    full = _normalize_url(href, page_url)
                    if full and full not in urls:
                        urls.append(full)
    except Exception as e:
        console.print(f"[yellow]R&D highlights year links: {e}[/yellow]")
    return urls


def follow_link_and_get_pdf_url(page, link_url: str, page_url: str) -> str | None:
    """
    Puntahan ang link_url; kung nag-redirect sa PDF o may PDF sa page, return ang PDF URL.
    """
    try:
        page.goto(link_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        # Direktang naka-navigate sa PDF
        if page.url and page.url.rstrip("/").lower().endswith(".pdf"):
            return page.url
        # May link o embed na PDF sa page
        for sel in ["a[href$='.pdf']", "embed[type='application/pdf']", "iframe[src*='.pdf']"]:
            el = page.locator(sel).first
            if el.count() > 0:
                src = el.get_attribute("href") or el.get_attribute("src")
                if src:
                    return _normalize_url(src, page.url)
        # Content-type PDF (e.g. inline display) – URL pa rin ang page
        if ".pdf" in (page.url or "").lower():
            return page.url
    except Exception:
        pass
    return None


def download_pdf(context, pdf_url: str, folder: str, index: int) -> bool:
    """
    Download PDF via context.request and save to folder. Returns True if saved or already existed.
    Huwag na i-download kung nandyan na ang file (para tama ang process, walang duplicate).
    """
    path = os.path.join(folder, _safe_filename(pdf_url, index))
    if os.path.isfile(path):
        console.print(f"[dim]Skip (file exists, no re-download): {os.path.basename(path)}[/dim]")
        return True
    try:
        response = context.request.get(pdf_url, timeout=90000)
        if response.status != 200:
            console.print(f"[yellow]HTTP {response.status} for {pdf_url}[/yellow]")
            return False
        body = response.body()
        if not body or len(body) < 100:
            console.print(f"[yellow]Empty or tiny response for {pdf_url}[/yellow]")
            return False
        with open(path, "wb") as f:
            f.write(body)
        console.print(f"[green]Saved: {path}[/green]")
        return True
    except Exception as e:
        console.print(f"[red]Download failed {pdf_url}: {e}[/red]")
        return False


def download_segment_pdfs(
    context,
    urls: list[str],
    completed: set[str],
    *,
    corpus_f=None,
) -> int:
    """
    Download new PDFs for a segment. When corpus_f is set (stream mode), process and
    append to corpus immediately, then delete PDF if configured.
    Returns total corpus records written this segment.
    """
    from src.openstat.services.philrice import ingest_pdf_to_corpus

    if not urls:
        return 0
    records_written = 0
    base_idx = len(completed)
    for j, pdf_url in enumerate(urls):
        if pdf_url in completed:
            console.print(f"[dim]  Skip (already completed): ...{pdf_url[-50:]}[/dim]")
            continue
        path = os.path.join(PHILRICE_PDFS_DIR, _safe_filename(pdf_url, base_idx + j))
        if os.path.isfile(path):
            if corpus_f is not None:
                records_written += ingest_pdf_to_corpus(path, corpus_f)
                completed.add(pdf_url)
                _save_checkpoint(completed)
            else:
                console.print(f"[dim]  Skip (file exists): {os.path.basename(path)}[/dim]")
                completed.add(pdf_url)
                _save_checkpoint(completed)
            continue
        console.print(f"[dim]  Downloading: {pdf_url[:80]}...[/dim]")
        if download_pdf(context, pdf_url, PHILRICE_PDFS_DIR, base_idx + j):
            if corpus_f is not None and os.path.isfile(path):
                records_written += ingest_pdf_to_corpus(path, corpus_f)
            completed.add(pdf_url)
            _save_checkpoint(completed)
        time.sleep(DELAY_PDF)
    return records_written


@require_internet
def run():
    from src.openstat.services.philrice import (
        delete_pdf_after_process,
        open_corpus_for_stream,
        stream_process_enabled,
    )

    console.rule("[bold cyan]PhilRice PDF Scraper")
    os.makedirs(PHILRICE_PDFS_DIR, exist_ok=True)
    completed = _load_checkpoint()
    stream = stream_process_enabled()
    if stream:
        console.print(
            "[dim]Stream mode: download → process → append corpus"
            + (" → delete PDF" if delete_pdf_after_process() else "")
            + "[/dim]"
        )
    if completed:
        console.print(
            f"[dim]Resume: {len(completed)} PDF(s) already completed in checkpoint.[/dim]"
        )

    corpus_f = None
    corpus_path = None
    total_stream_records = 0
    if stream:
        corpus_f, corpus_path = open_corpus_for_stream()

    all_pdf_urls = []
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

        page.set_default_timeout(60000)  # 1 min – sapat para mahina signal, hindi sobrang tagal
        time.sleep(2)

        def add_pdfs_from_page(current_url: str):
            links = collect_pdf_links_from_page(page, current_url)
            skipped = 0
            for u in links:
                if _should_skip_pdf(u):
                    skipped += 1
                    continue
                if u not in all_pdf_urls:
                    all_pdf_urls.append(u)
            return len(links), skipped

        # Laging main page muna (Downloads), tapos sub-pages – para ma-collect lahat (300+ PDFs) tulad ng una.
        urls_to_visit = PHILRICE_BASE_URLS + PHILRICE_SUB_PAGES
        console.print("[dim]Order: main (downloads, knowledge-products) muna, tapos sub-pages (rd-highlights, e-magazine, RS4DM, references, milestones).[/dim]")
        seen_pages = set()
        total_year_pdfs = 0  # global count for PDFs galing sa Previous R&D year links

        for base_url in urls_to_visit:
            console.print(f"[bold]Visiting: {base_url}[/bold]")
            try:
                segment_start = len(all_pdf_urls)  # mark start ng segment para sa base_url na ito
                page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                cur = base_url
                n, sk = add_pdfs_from_page(cur)
                console.print(f"[dim]This page: {n} PDF links ({sk} skipped), total so far: {len(all_pdf_urls)}[/dim]")

                # Pagination strategy:
                # - e-magazine / RS4DM / references: mas predictable ang URLs (page/2/, page/3/, ... page/8/).
                #   Mas safe na i-construct natin diretso imbes na sumunod sa UI na 1-3 + Last (na nagsho-show ng 4-8).
                # - iba (kung meron): fallback sa lumang go_to_next_pagination_page.
                if any(key in base_url.lower() for key in ["e-magazine", "rice-science-for-decision-makers", "databases/references", "databases/milestones"]):
                    max_pages = int(os.getenv("PHILRICE_MAX_PAGES", "12"))
                    for page_num in range(2, max_pages + 1):
                        candidate = urllib.parse.urljoin(base_url, f"page/{page_num}/")
                        try:
                            page.goto(candidate, wait_until="domcontentloaded", timeout=60000)
                            page.wait_for_timeout(3000)
                        except Exception:
                            break
                        # Kung hindi nagbago URL o nag-redirect sa base (walang ganitong page), stop na.
                        if page.url.rstrip("/") != candidate.rstrip("/"):
                            break
                        cur = page.url
                        n2, sk2 = add_pdfs_from_page(cur)
                        n += n2
                        sk += sk2
                        console.print(f"[dim]  Page {page_num}: +{n2} PDFs (section total: {n})[/dim]")
                        if n2 == 0:
                            # Kung wala nang bagong PDF sa page na ito, malamang wala nang susunod na page.
                            break
                else:
                    page_num = 1
                    while go_to_next_pagination_page(page, cur):
                        cur = page.url
                        page_num += 1
                        n2, sk2 = add_pdfs_from_page(cur)
                        n += n2
                        sk += sk2
                        console.print(f"[dim]  Page {page_num}: +{n2} PDFs (section total: {n})[/dim]")
                # R&D highlights: "Previous R and D highlights" – taon (2023, 2022, ...) pag pinindot, lalabas PDF
                if "rd-highlights" in base_url.lower():
                    page.goto(base_url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(4000)
                    year_links = collect_rd_highlights_previous_year_links(page, base_url)
                    if year_links:
                        console.print(f"[dim]Following {len(year_links)} year links (Previous R&D highlights)...[/dim]")
                    year_pdf_count = 0
                    for link in year_links:
                        pdf_url = follow_link_and_get_pdf_url(page, link, base_url)
                        if pdf_url and not _should_skip_pdf(pdf_url) and pdf_url not in all_pdf_urls:
                            all_pdf_urls.append(pdf_url)
                            year_pdf_count += 1
                            console.print(f"[dim]  PDF from year link: {pdf_url[:60]}...[/dim]")
                        time.sleep(DELAY_PAGE)
                    if year_pdf_count:
                        total_year_pdfs += year_pdf_count
                        console.print(f"[dim]  → {year_pdf_count} PDFs mula sa Previous R&D year links.[/dim]")
                # Kapag nasa main page (Downloads / knowledge-products), puntahan LAHAT ng dropdown/sub-section para makuha lahat ng PDF per button.
                is_main_page = base_url in PHILRICE_BASE_URLS or "downloads" in base_url.lower() or "knowledge-products" in base_url.lower()
                if is_main_page:
                    section_links = collect_internal_section_links(page, base_url)
                    # Lahat ng sub-link na puwedeng may PDF: Publications, R&D, Magazine, RS4DM, References, Stories, MOET, Fellowship, Journal, Photos, Videos, More Information Materials, etc.
                    download_keywords = [
                        "rd", "highlight", "magazine", "annual", "report", "knowledge", "reference", "rice", "upload", "database",
                        "stories", "news", "features", "moe", "fellowship", "journal", "biosystems", "author", "style", "guide",
                        "photos", "videos", "information", "materials", "form", "application", "thesis", "dissertation", "proposal",
                        "specials", "documenta", "decision", "makers", "milestones",
                    ]
                    # Huwag puntahan: about-us, contact, careers, bids (hindi downloads)
                    skip_paths = ("/about-us/", "contact", "careers", "bids")
                    relevant = [
                        u for u in section_links
                        if any(kw in u.lower() for kw in download_keywords) and not any(skip in u.lower() for skip in skip_paths)
                    ]
                    # Kung wala masyadong match, gamitin lahat ng section_links (maliban sa skip) para hindi mawala ang anumang dropdown
                    if len(relevant) < 5 and "downloads" in base_url.lower():
                        relevant = [u for u in section_links if not any(skip in u.lower() for skip in skip_paths)]
                    max_sub_visit = int(os.getenv("PHILRICE_MAX_SUB_VISIT", "80"))
                    for sub_url in relevant[:max_sub_visit]:
                        if sub_url in seen_pages:
                            continue
                        seen_pages.add(sub_url)
                        try:
                            console.print(f"[dim]  → Sub-button: {sub_url[:70]}...[/dim]")
                            page.goto(sub_url, wait_until="domcontentloaded", timeout=60000)
                            page.wait_for_timeout(5000)
                            cur = sub_url
                            n2, _ = add_pdfs_from_page(cur)
                            if n2:
                                console.print(f"[dim]    Found {n2} PDFs.[/dim]")

                            # Same numeric pagination strategy para sa sub-pages na magazine/RS4DM/references/milestones
                            if any(key in sub_url.lower() for key in ["e-magazine", "rice-science-for-decision-makers", "databases/references", "databases/milestones"]):
                                max_pages = int(os.getenv("PHILRICE_MAX_PAGES", "12"))
                                for page_num in range(2, max_pages + 1):
                                    candidate = urllib.parse.urljoin(sub_url, f"page/{page_num}/")
                                    try:
                                        page.goto(candidate, wait_until="domcontentloaded", timeout=60000)
                                        page.wait_for_timeout(3000)
                                    except Exception:
                                        break
                                    if page.url.rstrip("/") != candidate.rstrip("/"):
                                        break
                                    cur = page.url
                                    n3, _ = add_pdfs_from_page(cur)
                                    n2 += n3
                                    if n3:
                                        console.print(f"[dim]    Page {page_num}: +{n3} PDFs (sub-section total: {n2})[/dim]")
                                    else:
                                        break
                            else:
                                while go_to_next_pagination_page(page, cur):
                                    cur = page.url
                                    n3, _ = add_pdfs_from_page(cur)
                                    n2 += n3
                                    if n3:
                                        console.print(f"[dim]    Next page: {n3} PDFs.[/dim]")
                            if "rd-highlights" in sub_url.lower():
                                page.goto(sub_url, wait_until="domcontentloaded", timeout=60000)
                                page.wait_for_timeout(4000)
                                year_links = collect_rd_highlights_previous_year_links(page, sub_url)
                                sub_year_count = 0
                                for link in year_links:
                                    pdf_url = follow_link_and_get_pdf_url(page, link, sub_url)
                                    if pdf_url and not _should_skip_pdf(pdf_url) and pdf_url not in all_pdf_urls:
                                        all_pdf_urls.append(pdf_url)
                                        sub_year_count += 1
                                        console.print(f"[dim]    PDF from year: {pdf_url[:50]}...[/dim]")
                                    time.sleep(DELAY_PAGE)
                                if sub_year_count:
                                    total_year_pdfs += sub_year_count
                                    console.print(f"[dim]    → {sub_year_count} PDFs mula sa year links (sub-page).[/dim]")
                        except Exception as sub_err:
                            console.print(f"[dim]  Sub-button error: {sub_err}[/dim]")
                        try:
                            time.sleep(DELAY_PAGE)
                        except Exception:
                            pass

                # Pagkatapos ma-scrape lahat ng pages + year links para sa base_url na ito,
                # i-download agad lahat ng bagong PDF URLs sa segment na ito.
                segment_urls = [u for u in all_pdf_urls[segment_start:] if u not in completed]
                if segment_urls:
                    console.print(f"[bold]Downloading {len(segment_urls)} PDFs for section: {base_url}[/bold]")
                    total_stream_records += download_segment_pdfs(
                        context, segment_urls, completed, corpus_f=corpus_f
                    )

            except Exception as e:
                console.print(f"[yellow]Failed to load {base_url}: {e}[/yellow]")
            time.sleep(DELAY_PAGE)

        page.close()

        if total_year_pdfs:
            console.print(f"[bold dim]Total PDFs mula sa lahat ng R&D year links: {total_year_pdfs}[/bold dim]")

        # Safety net: kung sakaling may naiwan pang URLs na hindi na-download sa kahit anong segment.
        remaining = [u for u in all_pdf_urls if u not in completed]
        if remaining:
            console.print(f"[bold]Extra pass: downloading {len(remaining)} remaining PDFs (all sections).[/bold]")
            total_stream_records += download_segment_pdfs(
                context, remaining, completed, corpus_f=corpus_f
            )

        browser.close()

    if corpus_f is not None:
        corpus_f.close()
        console.print(f"[green]Stream corpus records this run: {total_stream_records}[/green]")
        console.print(f"[cyan]Corpus: {corpus_path}[/cyan]")

    console.rule("[bold green]Done")
    if not stream:
        console.print(f"PDFs saved to: [cyan]{os.path.abspath(PHILRICE_PDFS_DIR)}[/cyan]")
    else:
        left = list(Path(PHILRICE_PDFS_DIR).glob("*.pdf"))
        if left:
            console.print(
                f"[yellow]{len(left)} PDF(s) still on disk (process failed or delete off).[/yellow]"
            )
    console.print(f"Total completed (checkpoint): {len(completed)}")


if __name__ == "__main__":
    run()
