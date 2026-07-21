"""Tests for CSV-stream OpenSTAT price metadata snapshots."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from src.api.price_metadata_cache import build_price_snapshot_from_csv


class TestPriceMetadataFromCsv(unittest.TestCase):
    def test_streams_distinct_labels_without_loading_all_rows_as_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "openstat_table.csv"
            with path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(
                    fh,
                    fieldnames=[
                        "Geolocation",
                        "Commodity Type",
                        "Commodity",
                        "Year",
                        "Month",
                        "Price",
                    ],
                )
                writer.writeheader()
                writer.writerow(
                    {
                        "Geolocation": "Abra",
                        "Commodity Type": "Cereals",
                        "Commodity": "Palay",
                        "Year": "2023",
                        "Month": "August",
                        "Price": "24.0",
                    }
                )
                writer.writerow(
                    {
                        "Geolocation": "Abra",
                        "Commodity Type": "Cereals",
                        "Commodity": "Corn [White]",
                        "Year": "2023",
                        "Month": "Annual",
                        "Price": "20.0",
                    }
                )
                writer.writerow(
                    {
                        "Geolocation": "Laguna",
                        "Commodity Type": "Livestock",
                        "Commodity": "Pork",
                        "Year": "2024",
                        "Month": "January",
                        "Price": "150.0",
                    }
                )

            snapshot = build_price_snapshot_from_csv(path)

        self.assertEqual(snapshot.commodity_types, ("Cereals", "Livestock"))
        self.assertIn("Palay", snapshot.commodities_by_type["Cereals"])
        self.assertIn("Corn [White]", snapshot.commodities_by_type["Cereals"])
        self.assertIn("Pork", snapshot.commodities_by_type["Livestock"])
        self.assertEqual(snapshot.years, (2023, 2024))
        self.assertNotIn("Annual", snapshot.months)
        self.assertIn("August", snapshot.months)
        self.assertEqual(snapshot.geolocations, ("Abra", "Laguna"))


if __name__ == "__main__":
    unittest.main()
