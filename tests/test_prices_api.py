"""Tests for /v1/prices/* routes."""

from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from src.api.price_metadata_cache import PriceMetadataCache, build_price_snapshot_from_rows


def sample_price_rows() -> list[dict]:
    return [
        {
            "geolocation": "Abra",
            "commodity_type": "Cereals",
            "commodity": "Palay",
            "year": 2023,
            "month": "August",
            "price_php_per_kg": 24.0,
            "source": "openstat_psa",
            "text": "PSA farmgate price for Palay in Abra August 2023 was PHP 24.00 per kilogram.",
        },
        {
            "geolocation": "Abra",
            "commodity_type": "Cereals",
            "commodity": "Palay",
            "year": 2023,
            "month": "September",
            "price_php_per_kg": 23.5,
            "source": "openstat_psa",
            "text": "PSA farmgate price for Palay in Abra September 2023 was PHP 23.50 per kilogram.",
        },
    ]


def make_prices_client() -> tuple[TestClient, object]:
    os.environ.setdefault("API_AUTH_DISABLED", "true")
    os.environ.setdefault("API_LOG_JSON", "false")
    os.environ.setdefault("API_DOCS_ENABLED", "false")

    from src.api.app import create_app
    from src.api.deps import (
        get_price_metadata_cache,
        get_qdrant_store,
        reset_dependency_singletons,
    )
    from src.api.settings import get_settings
    from tests.fakes.fake_store import FakeQdrantStore

    reset_dependency_singletons()
    get_settings.cache_clear()

    fake = FakeQdrantStore()
    fake.seed_prices(sample_price_rows())

    cache = PriceMetadataCache()
    cache.set(build_price_snapshot_from_rows(sample_price_rows()))

    app = create_app()
    app.dependency_overrides[get_qdrant_store] = lambda: fake
    app.dependency_overrides[get_price_metadata_cache] = lambda: cache
    return TestClient(app), fake


class TestPricesRoutes(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.fake = make_prices_client()

    def test_list_prices(self) -> None:
        resp = self.client.get("/v1/prices?geolocation=Abra&year=2023&limit=10")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["items"][0]["commodity"], "Palay")

    def test_price_metadata(self) -> None:
        resp = self.client.get("/v1/prices/metadata")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn(2023, body["years"])
        self.assertIn("Abra", body["geolocations"])
        self.assertIn("Palay", body["commodities_by_type"]["Cereals"])

    def test_price_summary(self) -> None:
        resp = self.client.get("/v1/prices/summary?geolocation=Abra&commodity=Palay")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["overall"]["row_count"], 2)
        self.assertGreater(body["overall"]["avg_price_php_per_kg"], 0)

    def test_price_search(self) -> None:
        resp = self.client.post(
            "/v1/prices/search",
            json={"query": "palay farmgate price Abra August", "limit": 5},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertGreater(len(body["hits"]), 0)
        self.assertEqual(body["hits"][0]["geolocation"], "Abra")


if __name__ == "__main__":
    unittest.main()
