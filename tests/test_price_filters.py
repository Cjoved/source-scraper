"""Tests for price filter construction."""

from __future__ import annotations

import unittest

from src.api.errors import ApiError
from src.services.price_commodity_aliases import resolve_commodity_match_values
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


class PriceCommodityAliasTests(unittest.TestCase):
    def test_palay_expands_to_psa_paddy_labels(self) -> None:
        values = resolve_commodity_match_values("Palay")
        self.assertEqual(len(values), 2)
        self.assertTrue(all(v.startswith("Palay [Paddy]") for v in values))

    def test_exact_psa_label_passthrough(self) -> None:
        label = "Palay [Paddy] Fancy, dry (conv. to 14% mc)"
        self.assertEqual(resolve_commodity_match_values(label), [label])

    def test_bigas_maps_to_milled_rice(self) -> None:
        values = resolve_commodity_match_values("Bigas")
        self.assertTrue(any("WELL-MILLED" in v for v in values))
        self.assertFalse(any(v.startswith("Palay") for v in values))


if __name__ == "__main__":
    unittest.main()
