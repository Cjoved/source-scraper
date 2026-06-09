"""Tests for PhilRice News checkpoint / filename helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.openstat.scrapers.philrice_news import _date_count_from_existing_txt


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


if __name__ == "__main__":
    unittest.main()
