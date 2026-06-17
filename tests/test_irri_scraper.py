"""Tests for IRRI scraper filename/date helpers."""

from __future__ import annotations

import unittest

from src.openstat.scrapers.irri import (
    _all_news_mode,
    _clean_title_for_filename,
    _parse_date_from_text,
    _safe_filename_from_title_and_date,
)


class IrriScraperFilenameTests(unittest.TestCase):
    def test_all_news_mode_default(self) -> None:
        import os

        key = "IRRI_SKIP_COUNTRY_SEARCH"
        old = os.environ.pop(key, None)
        try:
            self.assertTrue(_all_news_mode())
        finally:
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old

    def test_parse_date_from_text_month_day_year(self) -> None:
        text = "Los Banos\n May 30, 2018\nSHARE\n\nArticle body here."
        self.assertEqual(_parse_date_from_text(text), "2018-05-30")

    def test_parse_date_from_text_day_month_year(self) -> None:
        text = "06 February 2018, Los Banos, Philippines — intro"
        self.assertEqual(_parse_date_from_text(text), "2018-02-06")

    def test_clean_title_strips_irri_suffix(self) -> None:
        title = "IRRI eyes DSR adoption | International Rice Research Institute"
        self.assertEqual(_clean_title_for_filename(title), "IRRI eyes DSR adoption")

    def test_safe_filename_from_title_and_date(self) -> None:
        existing: set[str] = set()
        fname = _safe_filename_from_title_and_date(
            "IRRI eyes DSR adoption | International Rice Research Institute",
            "2018-02-06",
            "https://www.irri.org/news-and-events/news/irri-eyes-public-private-sector-support-wider-dsr-adoption",
            existing,
        )
        self.assertEqual(fname, "IRRI eyes DSR adoption_2018-02-06.txt")

    def test_safe_filename_collision_suffix(self) -> None:
        existing = {"IRRI eyes DSR adoption_2018-02-06.txt"}
        fname = _safe_filename_from_title_and_date(
            "IRRI eyes DSR adoption | International Rice Research Institute",
            "2018-02-06",
            "https://www.irri.org/news-and-events/news/other-slug",
            existing,
        )
        self.assertEqual(fname, "IRRI eyes DSR adoption_2018-02-06_2.txt")


if __name__ == "__main__":
    unittest.main()
