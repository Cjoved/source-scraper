import unittest

import pandas as pd

from src.services.openstat_cpt import row_to_sentence, tabular_to_cpt_records


class OpenStatCptTests(unittest.TestCase):
    def test_row_to_sentence_with_price(self) -> None:
        row = pd.Series(
            {
                "Geolocation": "Abra",
                "Commodity": "Corngrain (Maize) White, matured",
                "Year": 2023,
                "Month": "August",
                "Price": 61.63,
            }
        )
        sentence = row_to_sentence(row)
        self.assertIn("August 2023", sentence)
        self.assertIn("Corngrain (Maize) White, matured", sentence)
        self.assertIn("Abra", sentence)
        self.assertIn("₱61.63 per kilogram", sentence)

    def test_row_to_sentence_missing_price(self) -> None:
        row = pd.Series(
            {
                "Geolocation": "Abra",
                "Commodity": "Palay",
                "Year": 2023,
                "Month": "August",
                "Price": float("nan"),
            }
        )
        sentence = row_to_sentence(row)
        self.assertIn("had no recorded data", sentence)

    def test_tabular_to_cpt_records_skips_annual_rows(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "Geolocation": "Abra",
                    "Commodity Type": "Cereals",
                    "Commodity": "Palay",
                    "Year": 2023,
                    "Month": "August",
                    "Price": 20.0,
                },
                {
                    "Geolocation": "Abra",
                    "Commodity Type": "Cereals",
                    "Commodity": "Palay",
                    "Year": 2023,
                    "Month": "Annual",
                    "Price": 19.5,
                },
            ]
        )
        records = tabular_to_cpt_records(df)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source"], "openstat")
        self.assertEqual(records[0]["month"], "August")


if __name__ == "__main__":
    unittest.main()
