from __future__ import annotations

import unittest

from src.services.textify import row_to_passage


class TestRowToPassage(unittest.TestCase):
    def test_canonical_row(self) -> None:
        row = {
            "year": 2018,
            "semester_code": 1,
            "semester_label": "1st Semester (Sept16-Mar15)",
            "region": "CAR",
            "province": "Abra",
            "municipality": "Bangued",
            "avg_yield_ton_ha": 3.03,
            "scraped_at": "2026-05-08T11:04:25",
        }
        passage = row_to_passage(row)
        self.assertIn("Bangued", passage)
        self.assertIn("Abra", passage)
        self.assertIn("CAR", passage)
        self.assertIn("3.03", passage)
        self.assertIn("2018", passage)
        self.assertIn("1st Semester", passage)
        self.assertIn("2026-05-08", passage)

    def test_handles_missing_municipality(self) -> None:
        row = {
            "year": 2020,
            "semester_code": 2,
            "semester_label": "2nd Semester (Mar16-Sept15)",
            "region": "Region III",
            "province": "Bulacan",
            "municipality": "",
            "avg_yield_ton_ha": 0,
            "scraped_at": "",
        }
        passage = row_to_passage(row)
        self.assertIn("(unknown municipality)", passage)
        self.assertIn("0.00", passage)


if __name__ == "__main__":
    unittest.main()
