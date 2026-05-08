import unittest
from pathlib import Path
import tempfile

from parsel import Selector

from src.formatter.prism_browser_tables_csv import append_browser_tables_csv
from src.scraper.parsers.prism_browser_tables import extract_tables_from_page, normalize_cell_text
from src.models.browser_model import PrismBrowserConfig


def _minimal_cfg(**kwargs: object) -> PrismBrowserConfig:
    defaults = dict(
        urls_raw="",
        scrapling_mode="stealth",
        headless=True,
        delay_page=2.0,
        min_content_len=100,
        resume_checkpoint=True,
        impersonate="chrome",
        use_http3=False,
        solve_cloudflare=True,
        content_selector="",
        adaptive=False,
        auto_save=False,
        stealth_fetcher_adaptive=True,
        rewrite_dataproducts=True,
        js_settle_seconds=8.0,
        save_corpus=True,
        export_tables_csv=True,
        tables_csv_path=Path("/tmp/unused.csv"),
        table_max_cols=32,
        jsonl_path=Path("/tmp/x.jsonl"),
        txt_dir=Path("/tmp/txt"),
        pdfs_dir=Path("/tmp/pdf"),
        checkpoint_path=Path("/tmp/ck.json"),
    )
    defaults.update(kwargs)
    return PrismBrowserConfig(**defaults)  # type: ignore[arg-type]


class TestNormalizeCell(unittest.TestCase):
    def test_nbsp(self) -> None:
        self.assertEqual(normalize_cell_text("a\u00a0b"), "a b")


class TestExtractTables(unittest.TestCase):
    def test_detail_info_table(self) -> None:
        html = """
        <html><body><div id="detail_info">
          <table><tr><th>H1</th><th>H2</th></tr><tr><td>1</td><td>2</td></tr></table>
        </div></body></html>
        """
        page = Selector(text=html)
        cfg = _minimal_cfg()
        norm = "https://prism.philrice.gov.ph/wp-dynamicreports/"
        tables = extract_tables_from_page(page, norm, cfg)
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0], [["H1", "H2"], ["1", "2"]])


class TestAppendTablesCsv(unittest.TestCase):
    def test_writes_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.csv"
            n = append_browser_tables_csv(
                p,
                source_url="https://example.com",
                page_title="T",
                scraped_at="now",
                tables=[[["a", "b"], ["1", "2"]]],
                max_cols=4,
            )
            self.assertEqual(n, 2)
            body = p.read_text(encoding="utf-8")
            self.assertIn("col_0", body)
            self.assertIn("a", body)


if __name__ == "__main__":
    unittest.main()
