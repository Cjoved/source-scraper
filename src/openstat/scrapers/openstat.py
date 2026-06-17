"""
OpenSTAT (PSA) scraper – Agri-Price data from openstat.psa.gov.ph.
Uses Playwright; Excel download → process (src.openstat.services.openstat) → CSV/CPT under data/openstat_processed/.
"""
from playwright.sync_api import sync_playwright
from src.openstat.utils import (
    require_internet,
    wait_for_selector_with_retry,
    wait_for_internet,
    get_cloudflare_cookies,
)
from src.openstat.scrapers.openstat_checkpoint import (
    load_completed_urls,
    merge_and_save_table_csv,
    normalize_openstat_url,
    parse_urls_env,
    save_completed_urls,
    tag_frames_with_source_url,
)
from src.openstat.config import data_path
from src.openstat.env_flags import openstat_enabled
from src.openstat.services.openstat import download_and_process_excel
from dotenv import load_dotenv
from rich.console import Console
from datetime import datetime
import os
import time

from src.openstat.utils.stealth import apply_page_stealth, stealth_available

HAS_STEALTH = stealth_available()

console = Console()
load_dotenv()
urls = os.getenv("URLS", "").split(",")
timestamp = datetime.now().strftime("%B%d,%Y_%H-%M-%S")

# OpenSTAT outputs under data/
SCRAPER_DOWNLOADS_DIR = data_path("openstat_downloads")
CHECKPOINT_PATH = data_path("checkpoints", "openstat_checkpoint.json")
TABLE_CSV_PATH = data_path("openstat_processed", "openstat_table.csv")


@require_internet
def select_dropdown_options(page, year_indexes, finalize=False):
    """Select all fixed dropdowns and optionally the year + Excel option"""
    selectors = [
        "#ctl00_ContentPlaceHolderMain_VariableSelector1_VariableSelector1_VariableSelectorValueSelectRepeater_ctl01_VariableValueSelect_VariableValueSelect_ValuesListBox",
        "#ctl00_ContentPlaceHolderMain_VariableSelector1_VariableSelector1_VariableSelectorValueSelectRepeater_ctl02_VariableValueSelect_VariableValueSelect_ValuesListBox",
        "#ctl00_ContentPlaceHolderMain_VariableSelector1_VariableSelector1_VariableSelectorValueSelectRepeater_ctl04_VariableValueSelect_VariableValueSelect_ValuesListBox",
    ]
    year_selector = "#ctl00_ContentPlaceHolderMain_VariableSelector1_VariableSelector1_VariableSelectorValueSelectRepeater_ctl03_VariableValueSelect_VariableValueSelect_ValuesListBox"

    for selector in selectors:
        wait_for_selector_with_retry(page, selector)
        page.eval_on_selector(selector, """
            el => {
                Array.from(el.options).forEach(opt => opt.selected = true);
                el.dispatchEvent(new Event('change'));
            }
        """)
        page.wait_for_timeout(1500)

    wait_for_selector_with_retry(page, year_selector)
    page.eval_on_selector(year_selector, """
        el => {
            Array.from(el.options).forEach(opt => opt.selected = false);
            el.dispatchEvent(new Event('change'));
        }
    """)
    for idx in year_indexes:
        page.eval_on_selector(year_selector, f"""
            el => {{
                el.options[{idx}].selected = true;
                el.dispatchEvent(new Event('change'));
            }}
        """)
        page.wait_for_timeout(500)

    if finalize:
        format_selector = "select#ctl00_ContentPlaceHolderMain_VariableSelector1_VariableSelector1_OutputFormats_OutputFormats_OutputFormatDropDownList"
        for attempt in range(3):
            try:
                page.select_option(format_selector, value="FileTypeExcelX", timeout=30000)
                break
            except Exception:
                if attempt == 2:
                    raise
                console.print(f"[yellow]Retrying Excel format selection (Attempt {attempt+2}/3)...[/yellow]")
                page.wait_for_timeout(3000)


def ensure_beginning_of_row_checked(page, variable_title: str):
    """Ticks 'Beginning of row' checkbox inside the variable panel."""
    panel = page.locator(
        f"xpath=//div[.//text()[contains(normalize-space(.), '{variable_title}')]]"
    ).first

    cb = panel.locator(
        "xpath=.//input[@type='checkbox' and (following-sibling::label[contains(., 'Beginning of row')] "
        "or parent::label[contains(., 'Beginning of row')] "
        "or @id=//label[contains(., 'Beginning of row')]/@for)]"
    ).first

    if cb.count() == 0:
        label = page.locator("xpath=//label[contains(., 'Beginning of row')]").first
        if label.count() == 0:
            return
        label.click()
        page.wait_for_timeout(300)
        return

    if not cb.is_checked():
        cb.check()
        page.wait_for_timeout(300)


MAX_YEARS_PER_SELECTION_SAFETY = 50
# Cap years per Excel submit — large exports often trigger PSA/Cloudflare 524 timeouts.
MAX_YEARS_PER_EXPORT = max(1, int(os.getenv("OPENSTAT_MAX_YEARS_PER_BATCH", "4")))


def _page_cloudflare_error(page) -> str | None:
    """Return Cloudflare error code if the page is a CF error (522/524), else None."""
    try:
        content = page.content()
    except Exception:
        return None
    for code in ("524", "522"):
        if f"Error code {code}" in content:
            return code
    if "Connection timed out" in content and "Cloudflare" in content:
        return "522"
    if "A timeout occurred" in content and "openstat.psa.gov.ph" in content:
        return "524"
    return None


def _page_is_cloudflare_522(page):
    return _page_cloudflare_error(page) == "522"


@require_internet
def scrape_all():
    if not openstat_enabled():
        console.print("[yellow]OPENSTAT=false. OpenSTAT scraper disabled. Set OPENSTAT=true in .env to run.[/yellow]")
        return
    if not urls or not any(u and u.strip() for u in urls):
        console.print("[yellow]URLS not set in .env. Add OpenSTAT URLs (comma-separated).[/yellow]")
        return

    all_data_frames = []
    urls_updated_this_run: set[str] = set()
    url_list = parse_urls_env()
    resume_checkpoint = os.getenv("RESUME_CHECKPOINT", "false").strip().lower() in ("true", "1", "yes")
    completed_urls_before_run: set[str] = set()
    console.rule(f"[bold cyan]Agri-Price Scraper (OpenSTAT) Started at {timestamp}")

    os.makedirs(SCRAPER_DOWNLOADS_DIR, exist_ok=True)
    downloads_path = os.path.abspath(SCRAPER_DOWNLOADS_DIR)

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-automation",
        "--disable-dev-shm-usage",
        "--no-first-run",
        "--no-default-browser-check",
        f'--download-default-directory="{downloads_path}"',
    ]

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=False,
                channel="chrome",
                args=launch_args,
            )
            console.print(f"[dim]Using Google Chrome. Excel downloads → {downloads_path}[/dim]")
        except Exception:
            try:
                browser = p.chromium.launch(
                    headless=False,
                    channel="msedge",
                    args=launch_args,
                )
                console.print(f"[dim]Using Microsoft Edge. Excel downloads → {downloads_path}[/dim]")
            except Exception:
                browser = p.chromium.launch(headless=False, args=launch_args)
                console.print(f"[dim]Using Chromium. Excel downloads → {downloads_path}[/dim]")

        first_url = next((u.strip() for u in urls if u and u.strip()), None)
        bypass_cookies, bypass_user_agent = get_cloudflare_cookies(first_url, log=lambda msg: console.print(msg))

        context_options = {
            "viewport": {"width": 1280, "height": 720},
            "locale": "en-PH",
            "ignore_https_errors": False,
            "java_script_enabled": True,
            "bypass_csp": False,
        }
        if bypass_user_agent:
            context_options["user_agent"] = bypass_user_agent
            console.print("[dim]Gamit ang User-Agent mula FlareSolverr.[/dim]")
        context = browser.new_context(**context_options)

        if bypass_cookies:
            try:
                context.add_cookies(bypass_cookies)
                console.print("[green]Cloudflare bypass: cookies injected.[/green]")
            except Exception as e:
                console.print(f"[dim]Bypass cookies skip: {e}[/dim]")
        else:
            console.print("[dim]Walang nakuha na bypass cookies. Maghintay sa Cloudflare o gamitin manual mode.[/dim]")

        page = context.new_page()

        if apply_page_stealth(page):
            console.print("[dim]Stealth evasions applied.[/dim]")
        elif not HAS_STEALTH:
            console.print(
                "[dim]playwright-stealth not installed — uv sync --extra openstat[/dim]"
            )

        page.set_default_timeout(60000)
        time.sleep(1)

        if resume_checkpoint:
            completed_urls = load_completed_urls(CHECKPOINT_PATH, url_list)
            completed_urls_before_run = set(completed_urls)
            if completed_urls:
                console.print(
                    f"[dim]Resume mode: skip {len(completed_urls)} completed URL(s) "
                    f"(checkpoint: {CHECKPOINT_PATH})[/dim]"
                )
        else:
            completed_urls = set()
            completed_urls_before_run = set()
            if os.path.isfile(CHECKPOINT_PATH):
                try:
                    os.remove(CHECKPOINT_PATH)
                    console.print("[dim]Checkpoint cleared (RESUME_CHECKPOINT=false).[/dim]")
                except Exception:
                    pass

        for url_index, url in enumerate(urls):
            if not url or not url.strip():
                continue
            url = normalize_openstat_url(url.strip())
            if not url:
                continue
            if resume_checkpoint and url in completed_urls:
                console.print(
                    f"[dim]Skipping URL {url_index + 1}/{len(urls)} (checkpoint): {url[:80]}…[/dim]"
                    if len(url) > 80
                    else f"[dim]Skipping URL {url_index + 1}/{len(urls)} (checkpoint): {url}[/dim]"
                )
                continue
            console.rule(f"[bold green]Processing URL {url_index + 1}/{len(urls)}")
            if not navigate_with_retries(page, url):
                console.print(f"[yellow]Skipping URL {url_index + 1} (connection timeout or Error 522).[/yellow]")
                continue
            try:
                wait_for_cloudflare_check(page, url_index)
            except Exception as e:
                console.print(f"[yellow]Skipping URL {url_index + 1} (Cloudflare check failed: {e}).[/yellow]")
                continue

            try:
                ensure_beginning_of_row_checked(page, "Geolocation")
                ensure_beginning_of_row_checked(page, "Commodity")
                ensure_beginning_of_row_checked(page, "Period")
            except Exception as e:
                console.print(f"[dim]Skipping 'Beginning of row' tweak (non-fatal): {e}[/dim]")

            year_selector = "#ctl00_ContentPlaceHolderMain_VariableSelector1_VariableSelector1_VariableSelectorValueSelectRepeater_ctl03_VariableValueSelect_VariableValueSelect_ValuesListBox"
            wait_for_selector_with_retry(page, year_selector, timeout=30000)
            total_years = page.eval_on_selector(year_selector, "el => el.options.length")
            console.print(f"[bold blue]Years available:[/bold blue] {total_years}")

            remaining_years = list(range(total_years))
            url_skipped_due_to_error = False
            url_data_frames = []

            while remaining_years:
                console.print(f"[dim]--- Batch: {len(remaining_years)} years remaining ---[/dim]")
                current_batch = []
                for year_idx in remaining_years:
                    if len(current_batch) >= MAX_YEARS_PER_SELECTION_SAFETY:
                        console.print(f"[dim]Safety cap ({MAX_YEARS_PER_SELECTION_SAFETY} years) reached.[/dim]")
                        break
                    test_batch = current_batch + [year_idx]
                    console.print(f"[dim]Testing selection: {len(test_batch)} years (adding year index {year_idx})[/dim]")

                    if not navigate_with_retries(page, url):
                        console.print(f"[yellow]Connection failed. Skipping rest of URL {url_index + 1}.[/yellow]")
                        remaining_years = []
                        url_skipped_due_to_error = True
                        break
                    try:
                        wait_for_cloudflare_check(page, url_index)
                    except Exception:
                        remaining_years = []
                        url_skipped_due_to_error = True
                        break
                    select_dropdown_options(page, test_batch)

                    try:
                        is_error = page.is_visible(
                            "#ctl00_ContentPlaceHolderMain_VariableSelector1_VariableSelector1_SelectionErrorlabel",
                            timeout=5000
                        )
                        if is_error:
                            console.print("[yellow]Site: 100k cells limit. Using previous selection.[/yellow]")
                            break
                        else:
                            current_batch = test_batch
                    except Exception as e:
                        console.print(f"[red]Error checking selection: {e}[/red]")
                        break

                if not current_batch:
                    if not remaining_years:
                        break
                    skipped = remaining_years.pop(0)
                    console.print(f"[red]Skipped year index: {skipped}[/red]")
                    continue

                if not navigate_with_retries(page, url):
                    console.print(f"[yellow]Connection failed. Skipping rest of URL {url_index + 1}.[/yellow]")
                    remaining_years = []
                    url_skipped_due_to_error = True
                else:
                    try:
                        wait_for_cloudflare_check(page, url_index)
                    except Exception:
                        remaining_years = []
                        url_skipped_due_to_error = True
                if not remaining_years:
                    break

                export_batch = current_batch
                if len(export_batch) > MAX_YEARS_PER_EXPORT:
                    overflow = export_batch[MAX_YEARS_PER_EXPORT:]
                    export_batch = export_batch[:MAX_YEARS_PER_EXPORT]
                    remaining_years = overflow + [
                        y for y in remaining_years if y not in current_batch
                    ]
                    console.print(
                        f"[dim]Export capped to {len(export_batch)} year(s) per submit "
                        f"(OPENSTAT_MAX_YEARS_PER_BATCH={MAX_YEARS_PER_EXPORT}) to reduce 524 timeouts.[/dim]"
                    )

                cf_code = _page_cloudflare_error(page)
                if cf_code:
                    console.print(
                        f"[yellow]Cloudflare {cf_code} on page — PSA origin timeout. "
                        f"Retry later or lower OPENSTAT_MAX_YEARS_PER_BATCH (now {MAX_YEARS_PER_EXPORT}).[/yellow]"
                    )
                    if cf_code == "524":
                        remaining_years = export_batch + [
                            y for y in remaining_years if y not in export_batch
                        ]
                        page.wait_for_timeout(15000)
                        continue

                select_dropdown_options(page, export_batch, finalize=True)
                commodity_selector = "#ctl00_ContentPlaceHolderMain_VariableSelector1_VariableSelector1_VariableSelectorValueSelectRepeater_ctl02_VariableValueSelect_VariableValueSelect_ValuesListBox"
                selected_commodity_labels = []
                try:
                    selected_commodity_labels = page.eval_on_selector(
                        commodity_selector,
                        "el => Array.from(el.options).filter(o => o.selected).map(o => o.text.trim())"
                    ) or []
                except Exception:
                    pass

                try:
                    cleaned_data = download_and_process_excel(
                        page, url_index, timestamp, urls,
                        selected_commodity_labels=selected_commodity_labels,
                    )
                    if cleaned_data is not None and not cleaned_data.empty:
                        url_data_frames.append(cleaned_data)
                        batch_rows = len(cleaned_data)
                        total_this_url = sum(len(df) for df in url_data_frames)
                        console.print(
                            f"[green]✔ Processed: {len(export_batch)} years "
                            f"(batch: {batch_rows} rows, total this URL: {total_this_url})[/green]"
                        )
                    else:
                        console.print("[yellow]No data returned for this batch[/yellow]")

                except Exception as e:
                    console.print(f"[red]Excel download error: {e}[/red]")

                remaining_years = [y for y in remaining_years if y not in export_batch]
                if remaining_years:
                    console.print(f"[dim]Remaining years: {len(remaining_years)}[/dim]")
                else:
                    console.print("[dim]All years for this URL done.[/dim]")

            all_data_frames.extend(tag_frames_with_source_url(url_data_frames, url))

            if not url_skipped_due_to_error and url_data_frames:
                completed_urls.add(url)
                urls_updated_this_run.add(url)
                save_completed_urls(CHECKPOINT_PATH, completed_urls)
                console.print(f"[dim]Checkpoint saved: {url[:80]}…[/dim]" if len(url) > 80 else f"[dim]Checkpoint saved: {url}[/dim]")
                # Progressive CSV — partial progress survives crash / deploy mid-run
                row_count = merge_and_save_table_csv(
                    all_data_frames,
                    table_csv_path=TABLE_CSV_PATH,
                    completed_urls_before_run=completed_urls_before_run,
                    urls_updated_this_run=urls_updated_this_run,
                    resume=resume_checkpoint,
                )
                if row_count is not None:
                    console.print(f"[dim]CSV updated ({len(row_count)} rows so far)[/dim]")
            elif not url_skipped_due_to_error and not url_data_frames:
                console.print(
                    f"[yellow]URL {url_index + 1} finished with no data — "
                    "not checkpointed (will retry on next run with RESUME_CHECKPOINT=true).[/yellow]"
                )

        browser.close()

    url_set = {u for u in url_list if u}
    if url_set and completed_urls >= url_set:
        try:
            if os.path.isfile(CHECKPOINT_PATH):
                os.remove(CHECKPOINT_PATH)
                console.print("[dim]All URLs complete — checkpoint cleared for next scheduled run.[/dim]")
        except OSError:
            pass

    if urls_updated_this_run:
        console.print(
            f"[bold green]✔ OpenSTAT table CSV: {TABLE_CSV_PATH} "
            f"({len(urls_updated_this_run)} URL(s) updated this run)[/bold green]"
        )
    elif resume_checkpoint and completed_urls_before_run:
        console.print(
            "[dim]No new rows this run; existing openstat_table.csv kept "
            f"({len(completed_urls_before_run)} URL(s) in checkpoint).[/dim]"
        )
    else:
        console.print("[bold red]No data was scraped![/bold red]")

    console.rule("[bold cyan]OpenSTAT Scraper Finished")


def wait_for_cloudflare_check(page, url_index, timeout=300000):
    """Hintayin ang Cloudflare: auto-verification o manual 'Verify you are human'."""
    year_selector = "#ctl00_ContentPlaceHolderMain_VariableSelector1_VariableSelector1_VariableSelectorValueSelectRepeater_ctl03_VariableValueSelect_VariableValueSelect_ValuesListBox"
    try:
        page.wait_for_selector(year_selector, timeout=8000)
        return
    except Exception:
        pass
    console.print("[dim]Cloudflare detected. Waiting up to 20s for auto-verify...[/dim]")
    for _ in range(4):
        time.sleep(5)
        try:
            if page.query_selector(year_selector):
                console.print("[green]In. Continuing scrape.[/green]")
                return
        except Exception:
            pass
    console.print("[yellow]If you see 'Verify you are human', click the checkbox. Waiting up to 5 min...[/yellow]")
    try:
        page.wait_for_selector(year_selector, timeout=timeout)
        console.print("[green]In. Continuing.[/green]")
    except Exception as e:
        console.print(f"[red]Timeout: {e}[/red]")
        console.print("[yellow]Manual mode: download in browser, put files in data/manual_downloads, then: python -m src.services.openstat (and call process_manual_downloads)[/yellow]")
        raise


MAX_NAV_ATTEMPTS = 4


def navigate_with_retries(page, url, timeout=45000):
    """Navigate to URL with retries. Returns True on success, False to skip URL."""
    attempt = 1
    while attempt <= MAX_NAV_ATTEMPTS:
        try:
            print(f"→ Navigating (Attempt {attempt}/{MAX_NAV_ATTEMPTS})...")
            page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            page.wait_for_load_state("load", timeout=30000)
            cf_code = _page_cloudflare_error(page)
            if cf_code in ("522", "524"):
                console.print(
                    f"[yellow]Cloudflare Error {cf_code}. Retry {attempt}/{MAX_NAV_ATTEMPTS}.[/yellow]"
                )
                attempt += 1
                time.sleep(5)
                continue
            return True
        except Exception as e:
            err_str = str(e)
            print(f"Navigation error: {e}")

            if "Target" in err_str and "closed" in err_str:
                console.print("[red]Browser closed. Do not close the window while scraping.[/red]")
                raise

            if "ERR_NAME_NOT_RESOLVED" in err_str or "ERR_NETWORK_CHANGED" in err_str or "net::ERR_INTERNET_DISCONNECTED" in err_str:
                print("⚠ Internet lost. Waiting to reconnect...")
                wait_for_internet()
                try:
                    page.reload(timeout=timeout, wait_until="domcontentloaded")
                    page.wait_for_load_state("load", timeout=30000)
                    return True
                except Exception as reload_error:
                    print(f"Reload failed: {reload_error}")
            elif "Timeout" in err_str:
                console.print(f"[yellow]Timeout (attempt {attempt}/{MAX_NAV_ATTEMPTS}).[/yellow]")
            else:
                print(f"Unexpected error. Retrying... ({e})")

            if attempt >= MAX_NAV_ATTEMPTS:
                console.print(f"[red]Failed after {MAX_NAV_ATTEMPTS} attempts. Skipping this URL.[/red]")
                return False
            time.sleep(5)
            attempt += 1
    return False


if __name__ == "__main__":
    scrape_all()
