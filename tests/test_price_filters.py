"""Tests for price filter construction."""

from __future__ import annotations

import unittest

from src.api.errors import ApiError
from src.services.price_filters import build_price_filter


class PriceFilterTests(unittest.TestCase):
    def test_invalid_year_range_raises(self) -> None:
        with self.assertRaises(ApiError):
            build_price_filter(year_min=2025, year_max=2020)

    def test_invalid_price_range_raises(self) -> None:
        with self.assertRaises(ApiError):
            build_price_filter(min_price=50.0, max_price=10.0)

    def test_builds_filter_with_stripped_strings(self) -> None:
        flt = build_price_filter(geolocation=" Abra ", commodity=" Palay ")
        self.assertEqual(flt.geolocation, "Abra")
        self.assertEqual(flt.commodity, "Palay")


if __name__ == "__main__":
    unittest.main()
