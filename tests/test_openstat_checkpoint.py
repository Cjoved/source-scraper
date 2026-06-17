"""Tests for OpenSTAT URL checkpoint + CSV merge."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.openstat.scrapers.openstat_checkpoint import (
    load_completed_urls,
    merge_and_save_table_csv,
    normalize_openstat_url,
    save_completed_urls,
    tag_frames_with_source_url,
)


class OpenstatCheckpointTests(unittest.TestCase):
    def test_normalize_openstat_url_strips_query_and_slash(self) -> None:
        a = normalize_openstat_url("https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__1/")
        b = normalize_openstat_url("https://openstat.psa.gov.ph/PXWeb/pxweb/en/DB/DB__1/?foo=1")
        self.assertEqual(a, b)

    def test_migrate_legacy_indices_to_urls(self) -> None:
        url_a = "https://openstat.psa.gov.ph/page/cereals/"
        url_b = "https://openstat.psa.gov.ph/page/rootcrops/"
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "openstat_checkpoint.json"
            ckpt.write_text(json.dumps({"completed_url_indices": [0, 1]}), encoding="utf-8")
            done = load_completed_urls(
                ckpt,
                [normalize_openstat_url(url_a), normalize_openstat_url(url_b)],
            )
            self.assertEqual(
                done,
                {normalize_openstat_url(url_a), normalize_openstat_url(url_b)},
            )
            saved = json.loads(ckpt.read_text(encoding="utf-8"))
            self.assertIn("completed_urls", saved)
            self.assertNotIn("completed_url_indices", saved)

    def test_resume_merge_keeps_skipped_url_rows(self) -> None:
        url_a = normalize_openstat_url("https://openstat.psa.gov.ph/page/cereals/")
        url_b = normalize_openstat_url("https://openstat.psa.gov.ph/page/rootcrops/")
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "openstat_table.csv"
            old = pd.DataFrame(
                [
                    {
                        "Geolocation": "Region I",
                        "Commodity Type": "Cereals",
                        "Commodity": "Palay",
                        "Year": 2024,
                        "Month": "January",
                        "Price": 25.0,
                        "Source URL": url_a,
                    }
                ]
            )
            old.to_csv(csv_path, index=False)

            new_frame = pd.DataFrame(
                [
                    {
                        "Geolocation": "Region II",
                        "Commodity Type": "Rootcrops",
                        "Commodity": "Cassava",
                        "Year": 2024,
                        "Month": "February",
                        "Price": 18.0,
                    }
                ]
            )
            tagged = tag_frames_with_source_url([new_frame], url_b)

            result = merge_and_save_table_csv(
                tagged,
                table_csv_path=csv_path,
                completed_urls_before_run={url_a},
                urls_updated_this_run={url_b},
                resume=True,
            )
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(len(result), 2)
            commodities = set(result["Commodity"].tolist())
            self.assertEqual(commodities, {"Palay", "Cassava"})

    def test_full_run_replaces_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "openstat_table.csv"
            pd.DataFrame([{"Geolocation": "Old", "Commodity": "X", "Year": 2020, "Month": "Jan", "Price": 1}]).to_csv(
                csv_path, index=False
            )
            new_frame = pd.DataFrame(
                [
                    {
                        "Geolocation": "Region I",
                        "Commodity Type": "Cereals",
                        "Commodity": "Palay",
                        "Year": 2024,
                        "Month": "March",
                        "Price": 30.0,
                        "Source URL": normalize_openstat_url("https://openstat.psa.gov.ph/page/cereals/"),
                    }
                ]
            )
            result = merge_and_save_table_csv(
                [new_frame],
                table_csv_path=csv_path,
                completed_urls_before_run=set(),
                urls_updated_this_run=set(),
                resume=False,
            )
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(len(result), 1)
            self.assertEqual(result.iloc[0]["Commodity"], "Palay")

    def test_save_completed_urls_writes_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = Path(tmp) / "ckpt.json"
            raw = "https://OpenStat.PSA.gov.ph/DB/DB__1/?x=1"
            save_completed_urls(ckpt, {raw})
            data = json.loads(ckpt.read_text(encoding="utf-8"))
            self.assertEqual(data["completed_urls"], [normalize_openstat_url(raw)])


if __name__ == "__main__":
    unittest.main()
