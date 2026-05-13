from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.api.settings import get_settings
from src.indexing.yield_indexer import normalize_csv_row, run_indexer
from src.scraper.prism_constants import CSV_COLUMNS
from tests.fakes.fake_store import FakeQdrantStore


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class TestNormalizeCsvRow(unittest.TestCase):
    def test_canonical(self) -> None:
        normalized = normalize_csv_row(
            {
                "Year": "2018",
                "Semester": "1st Semester (Sept16-Mar15)",
                "Region": "CAR",
                "Province": "Abra",
                "Municipality": "Bangued",
                "Average Yield (ton/ha)": "3.03",
                "Date and time of Scraping": "2026-05-08 11:04:25",
            },
            schema_version="v1",
        )
        assert normalized is not None
        self.assertEqual(normalized["year"], 2018)
        self.assertEqual(normalized["semester_code"], 1)
        self.assertEqual(normalized["avg_yield_ton_ha"], 3.03)
        self.assertIn("T", normalized["scraped_at"])

    def test_rejects_invalid(self) -> None:
        self.assertIsNone(
            normalize_csv_row(
                {
                    "Year": "abc",
                    "Semester": "1st Semester (Sept16-Mar15)",
                    "Region": "CAR",
                    "Province": "Abra",
                    "Municipality": "Bangued",
                    "Average Yield (ton/ha)": "3.03",
                    "Date and time of Scraping": "",
                },
                schema_version="v1",
            )
        )


class TestRunIndexer(unittest.TestCase):
    def test_writes_to_both_collections(self) -> None:
        get_settings.cache_clear()
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "yield.csv"
            _write_csv(
                csv_path,
                [
                    {
                        "Year": "2019",
                        "Semester": "1st Semester (Sept16-Mar15)",
                        "Region": "CAR",
                        "Province": "Abra",
                        "Municipality": "Bangued",
                        "Average Yield (ton/ha)": "3.0",
                        "Date and time of Scraping": "2026-05-08 11:04:25",
                    },
                    {
                        "Year": "2019",
                        "Semester": "2nd Semester (Mar16-Sept15)",
                        "Region": "CAR",
                        "Province": "Abra",
                        "Municipality": "Bucay",
                        "Average Yield (ton/ha)": "4.0",
                        "Date and time of Scraping": "2026-05-08 11:04:25",
                    },
                ],
            )
            store = FakeQdrantStore()
            stats = run_indexer(
                csv_path=csv_path,
                store=store,
                settings=get_settings(),
                batch_size=2,
            )
            self.assertEqual(stats.rows_seen, 2)
            self.assertEqual(stats.records_upserted, 2)
            self.assertEqual(stats.knowledge_upserted, 2)
            self.assertTrue(store.created_collections)
            self.assertEqual(len(store.records), 2)
            self.assertEqual(len(store.knowledge), 2)
            for payload in store.knowledge.values():
                self.assertIn("text", payload)


if __name__ == "__main__":
    unittest.main()
