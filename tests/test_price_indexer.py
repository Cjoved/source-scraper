"""Tests for OpenSTAT price CSV indexer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.indexing.price_indexer import normalize_csv_row, run_price_indexer
from src.storage.qdrant_store import build_price_point_id
from tests.fakes.fake_store import FakeQdrantStore


class PriceIndexerTests(unittest.TestCase):
    def test_normalize_csv_row(self) -> None:
        row = normalize_csv_row(
            {
                "Geolocation": "Abra",
                "Commodity Type": "Cereals",
                "Commodity": "Palay",
                "Year": "2023",
                "Month": "August",
                "Price": "24.0",
            },
            schema_version="v1",
        )
        assert row is not None
        self.assertEqual(row["geolocation"], "Abra")
        self.assertEqual(row["commodity"], "Palay")
        self.assertEqual(row["year"], 2023)
        self.assertEqual(row["month"], "August")
        self.assertEqual(row["price_php_per_kg"], 24.0)

    def test_normalize_skips_annual_rows(self) -> None:
        row = normalize_csv_row(
            {
                "Geolocation": "Abra",
                "Commodity Type": "Cereals",
                "Commodity": "Palay",
                "Year": "2023",
                "Month": "Annual",
                "Price": "20.0",
            },
            schema_version="v1",
        )
        self.assertIsNone(row)

    def test_build_price_point_id_stable(self) -> None:
        a = build_price_point_id("Abra", "Palay", 2023, "August")
        b = build_price_point_id("Abra", "Palay", 2023, "August")
        self.assertEqual(a, b)
        self.assertNotEqual(a, build_price_point_id("Abra", "Palay", 2023, "September"))

    def test_run_price_indexer_upserts_both_collections(self) -> None:
        csv_content = (
            "Geolocation,Commodity Type,Commodity,Year,Month,Price\n"
            "Abra,Cereals,Palay,2023,August,24.0\n"
            "Abra,Cereals,Palay,2023,September,23.5\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "openstat_table.csv"
            path.write_text(csv_content, encoding="utf-8")
            store = FakeQdrantStore()
            from src.api.settings import Settings

            stats = run_price_indexer(
                csv_path=path,
                store=store,
                settings=Settings(),
            )
            self.assertEqual(stats.rows_seen, 2)
            self.assertEqual(stats.records_upserted, 2)
            self.assertEqual(stats.knowledge_upserted, 2)
            self.assertEqual(len(store.price_records), 2)
            self.assertEqual(len(store.price_knowledge), 2)


if __name__ == "__main__":
    unittest.main()
