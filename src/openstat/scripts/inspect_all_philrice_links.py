"""
Inspect PhilRice pages (e-magazine, rd-highlights, etc.) – href/buttons for PDF links.
Run from project root: python -m src.scripts.inspect_all_philrice_links
"""
from playwright.sync_api import sync_playwright
import json
import os
from src.openstat.config import data_path

URLS = [
    "https://www.philrice.gov.ph/e-magazine/",
    "https://www.philrice.gov.ph/databases/rd-highlights/",
    "https://www.philrice.gov.ph/databases/rice-science-for-decision-makers/",
    "https://www.philrice.gov.ph/databases/references/",
    "https://www.philrice.gov.ph/databases/milestones/",
]

def inspect_page(page, url: str) -> list:
    links_info = []
    for a in page.locator("a[href]").all():
        text = (a.inner_text() or "").strip()
        href = a.get_attribute("href")
        cls = a.get_attribute("class") or ""
        download_attr = a.get_attribute("download")
        if not href:
            continue
        is_read_dl = "read" in text.lower() or "download" in text.lower()
        is_pdf = ".pdf" in href.lower() or "wpdmdl" in href.lower()
        is_year = text.strip().isdigit() or (len(text) in (4, 9) and "20" in text)
        if not (is_read_dl or is_pdf or is_year):
            continue
        try:
            html = a.evaluate("el => el.outerHTML").strip()[:600]
        except Exception:
            html = ""
        links_info.append({
            "text": text,
            "href": href,
            "class": cls,
            "download": download_attr,
            "html_sample": html,
        })
    return links_info

def main():
    all_results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_default_timeout(25000)
        for url in URLS:
            name = url.rstrip("/").split("/")[-1] or "index"
            print("\n" + "=" * 70)
            print(f"PAGE: {url}")
            print("=" * 70)
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                links = inspect_page(page, url)
                all_results[name] = {"url": url, "links": links}
                for i, L in enumerate(links):
                    print("-" * 60)
                    print(f"[{i+1}] Text: {L['text']!r}")
                    print(f"    href: {L['href'][:100]}{'...' if len(L['href'])>100 else ''}")
                    print(f"    class: {L['class']!r}  download: {L['download']!r}")
                    print(f"    HTML: {L['html_sample'][:350]}...")
                print(f"\nTotal Read/Download/PDF/Year links: {len(links)}")
            except Exception as e:
                print(f"Error: {e}")
                all_results[name] = {"url": url, "error": str(e), "links": []}
        browser.close()

    out_path = data_path("philrice_all_links_inspect.json")
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print("\nSaved:", out_path)

if __name__ == "__main__":
    main()
