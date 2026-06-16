"""Tests for OpenSTAT price passage textifier."""

from __future__ import annotations

import unittest

from src.services.price_textify import row_to_passage


class PriceTextifyTests(unittest.TestCase):
    def test_single_sentence_no_duplicate_header(self) -> None:
        row = {
            "geolocation": "Laguna",
            "commodity_type": "Cereals",
            "commodity": "Corngrain [Maize] White, matured",
            "year": 2023,
            "month": "January",
            "price_php_per_kg": 22.22,
        }
        text = row_to_passage(row)
        self.assertEqual(text.count("January 2023"), 1)
        self.assertEqual(text.count("Corngrain [Maize] White, matured"), 1)
        self.assertEqual(text.count("Laguna"), 1)
        self.assertIn("₱22.22 per kilogram", text)
        self.assertIn("(Source: PSA OpenSTAT, Cereals)", text)
        self.assertNotIn("openstat.psa.gov.ph", text)

    def test_missing_price(self) -> None:
        row = {
            "geolocation": "Abra",
            "commodity_type": "Cereals",
            "commodity": "Palay",
            "year": 2023,
            "month": "March",
            "price_php_per_kg": None,
        }
        text = row_to_passage(row)
        self.assertIn("had no recorded data", text)
        self.assertNotIn("₱", text)


if __name__ == "__main__":
    unittest.main()
