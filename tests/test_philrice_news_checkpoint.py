"""Tests for PhilRice News checkpoint / filename helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.openstat.scrapers.philrice_news import (
    PhilRiceNewsScrapeStatus,
    _existing_txt_filenames,
    _load_checkpoint_state,
    _page_is_not_found,
    _posted_date_to_iso,
    _safe_filename_from_title_and_date,
    _write_scrape_status,
)


class PhilriceNewsCheckpointTests(unittest.TestCase):
    def test_posted_date_to_iso(self) -> None:
        self.assertEqual(_posted_date_to_iso("03-11-26"), "2026-03-11")

    def test_safe_filename_from_title_and_date(self) -> None:
        existing: set[str] = set()
        fname = _safe_filename_from_title_and_date(
            "Rice training expands extension support",
            "03-11-26",
            "https://www.philrice.gov.ph/rice-training-expands-extension-support/",
            existing,
        )
        self.assertEqual(fname, "Rice training expands extension support_2026-03-11.txt")
        self.assertIn(fname, existing)

    def test_safe_filename_collision_suffix(self) -> None:
        existing = {"Rice training expands extension support_2026-03-11.txt"}
        fname = _safe_filename_from_title_and_date(
            "Rice training expands extension support",
            "03-11-26",
            "https://www.philrice.gov.ph/other-article/",
            existing,
        )
        self.assertEqual(fname, "Rice training expands extension support_2026-03-11_2.txt")

    def test_safe_filename_fallback_to_url_slug(self) -> None:
        existing: set[str] = set()
        fname = _safe_filename_from_title_and_date(
            "",
            "06-04-26",
            "https://www.philrice.gov.ph/training-expands-extension-support/",
            existing,
        )
        self.assertEqual(fname, "training-expands-extension-support_2026-06-04.txt")

    def test_existing_txt_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Article A_2026-06-04.txt").write_text("a", encoding="utf-8")
            (root / "Article B_2026-03-11.txt").write_text("b", encoding="utf-8")
            names = _existing_txt_filenames(root)
            self.assertEqual(
                names,
                {"Article A_2026-06-04.txt", "Article B_2026-03-11.txt"},
            )

    def test_existing_txt_filenames_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_existing_txt_filenames(Path(tmp)), set())

    def test_legacy_checkpoint_without_file_map_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            news = Path(tmp) / "news"
            news.mkdir()
            ckpt = Path(tmp) / "ckpt.json"
            ckpt.write_text(
                '{"scraped_urls": ["https://www.philrice.gov.ph/foo"], "url_to_file": {}}',
                encoding="utf-8",
            )
            (news / "Sample headline_2026-01-01.txt").write_text("x", encoding="utf-8")

            import src.openstat.scrapers.philrice_news as mod

            old_news = mod.PHILRICE_NEWS_DIR
            old_ckpt = mod.CHECKPOINT_PATH
            try:
                mod.PHILRICE_NEWS_DIR = str(news)
                mod.CHECKPOINT_PATH = ckpt
                urls, mapping, dead = _load_checkpoint_state()[:3]
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
                '"url_to_file": {"https://www.philrice.gov.ph/a": "Old headline_2026-01-01.txt"}}',
                encoding="utf-8",
            )

            import src.openstat.scrapers.philrice_news as mod

            old_news = mod.PHILRICE_NEWS_DIR
            old_ckpt = mod.CHECKPOINT_PATH
            try:
                mod.PHILRICE_NEWS_DIR = str(news)
                mod.CHECKPOINT_PATH = ckpt
                urls, mapping, dead = _load_checkpoint_state()[:3]
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
