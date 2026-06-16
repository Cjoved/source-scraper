"""Tests for PhilRice News checkpoint / filename helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.openstat.scrapers.philrice_news import (
    PhilRiceNewsScrapeStatus,
    _date_count_from_existing_txt,
    _load_checkpoint_state,
    _page_is_not_found,
    _write_scrape_status,
)


class PhilriceNewsCheckpointTests(unittest.TestCase):
    def test_date_count_from_existing_txt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "philrice_news_06-04-26.txt").write_text("a", encoding="utf-8")
            (root / "philrice_news_06-04-26_2.txt").write_text("b", encoding="utf-8")
            (root / "philrice_news_03-11-26.txt").write_text("c", encoding="utf-8")
            counts = _date_count_from_existing_txt(root)
            self.assertEqual(counts["06-04-26"], 2)
            self.assertEqual(counts["03-11-26"], 1)

    def test_date_count_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_date_count_from_existing_txt(Path(tmp)), {})

    def test_legacy_checkpoint_without_file_map_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            news = Path(tmp) / "news"
            news.mkdir()
            ckpt = Path(tmp) / "ckpt.json"
            ckpt.write_text(
                '{"scraped_urls": ["https://www.philrice.gov.ph/foo"], "url_to_file": {}}',
                encoding="utf-8",
            )
            (news / "philrice_news_01-01-26.txt").write_text("x", encoding="utf-8")

            import src.openstat.scrapers.philrice_news as mod

            old_news = mod.PHILRICE_NEWS_DIR
            old_ckpt = mod.CHECKPOINT_PATH
            try:
                mod.PHILRICE_NEWS_DIR = str(news)
                mod.CHECKPOINT_PATH = ckpt
                urls, mapping, dead = _load_checkpoint_state()
            finally:
                mod.PHILRICE_NEWS_DIR = old_news
                mod.CHECKPOINT_PATH = old_ckpt

            self.assertEqual(urls, [])
            self.assertEqual(mapping, {})
            self.assertEqual(dead, set())

    def test_checkpoint_repairs_missing_txt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            news = Path(tmp) / "news"
            news.mkdir()
            ckpt = Path(tmp) / "ckpt.json"
            ckpt.write_text(
                '{"scraped_urls": ["https://www.philrice.gov.ph/a"], '
                '"url_to_file": {"https://www.philrice.gov.ph/a": "philrice_news_01-01-26.txt"}}',
                encoding="utf-8",
            )

            import src.openstat.scrapers.philrice_news as mod

            old_news = mod.PHILRICE_NEWS_DIR
            old_ckpt = mod.CHECKPOINT_PATH
            try:
                mod.PHILRICE_NEWS_DIR = str(news)
                mod.CHECKPOINT_PATH = ckpt
                urls, mapping, dead = _load_checkpoint_state()
            finally:
                mod.PHILRICE_NEWS_DIR = old_news
                mod.CHECKPOINT_PATH = old_ckpt

            self.assertEqual(urls, [])
            self.assertEqual(mapping, {})
            self.assertEqual(dead, set())

    def test_page_is_not_found_detects_nginx_404(self) -> None:
        class FakePage:
            def title(self) -> str:
                return "404 Not Found"

            def locator(self, _sel: str):
                return self

            def inner_text(self, timeout: int = 0) -> str:
                return "404 Not Found\nnginx"

        self.assertTrue(_page_is_not_found(FakePage()))

    def test_write_scrape_status_accepts_str_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            import src.openstat.scrapers.philrice_news as mod

            status_path = Path(tmp) / "status.json"
            old = mod.SCRAPE_STATUS_PATH
            try:
                mod.SCRAPE_STATUS_PATH = str(status_path)
                _write_scrape_status(
                    PhilRiceNewsScrapeStatus(
                        site_total=991,
                        verified_urls=637,
                        dead_urls=5,
                        txt_files=637,
                        fetched_this_run=0,
                        skipped_checkpoint=637,
                        incomplete=True,
                    )
                )
            finally:
                mod.SCRAPE_STATUS_PATH = old
            self.assertTrue(status_path.is_file())


if __name__ == "__main__":
    unittest.main()
