from __future__ import annotations

import unittest

from tests.helpers import make_client, sample_rows


class TestHealthRoute(unittest.TestCase):
    def test_health_ok(self) -> None:
        client, _ = make_client()
        resp = client.get("/v1/health")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["qdrant"], "reachable")

    def test_health_unreachable_returns_503(self) -> None:
        client, fake = make_client()
        fake.reachable = False
        resp = client.get("/v1/health")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"]["code"], "QDRANT_UNAVAILABLE")


class TestYieldRoute(unittest.TestCase):
    def test_list_no_filter(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.get("/v1/yield")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 4)
        self.assertEqual(len(body["items"]), 4)

    def test_list_with_region_filter(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.get("/v1/yield", params={"region": "CAR"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["total"], 3)
        regions = {item["region"] for item in body["items"]}
        self.assertEqual(regions, {"CAR"})

    def test_list_pagination(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.get("/v1/yield", params={"limit": 2, "offset": 0})
        body = resp.json()
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["next_offset"], 2)


class TestMetadataRoute(unittest.TestCase):
    def test_metadata(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.get("/v1/yield/metadata")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn(2019, body["years"])
        self.assertIn(2020, body["years"])
        self.assertIn("CAR", body["regions"])
        self.assertIn("Abra", body["provinces_by_region"]["CAR"])
        self.assertIn("Bangued", body["municipalities_by_region_province"]["CAR"]["Abra"])
        self.assertIn("Bucay", body["municipalities_by_region_province"]["CAR"]["Abra"])


class TestSummaryRoute(unittest.TestCase):
    def test_summary_province(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.get("/v1/yield/summary", params={"province": "Abra"})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["overall"]["row_count"], 2)
        self.assertAlmostEqual(body["overall"]["avg_yield_ton_ha"], 3.5, places=4)

    def test_summary_year_range_invalid(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.get(
            "/v1/yield/summary",
            params={"year_min": 2025, "year_max": 2020},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "INVALID_FILTER")


class TestExportRoute(unittest.TestCase):
    def test_ndjson_stream(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.get("/v1/yield/export", params={"format": "ndjson"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/x-ndjson", resp.headers["content-type"])
        lines = [line for line in resp.text.splitlines() if line]
        self.assertEqual(len(lines), 4)

    def test_csv_stream(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.get("/v1/yield/export", params={"format": "csv"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers["content-type"])
        lines = [line for line in resp.text.splitlines() if line]
        self.assertEqual(len(lines), 5)
        self.assertTrue(lines[0].startswith("year,"))


class TestKnowledgeRoute(unittest.TestCase):
    def test_search_returns_hits(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.post(
            "/v1/knowledge/search",
            json={
                "query": "Bangued Abra",
                "limit": 5,
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertGreater(len(body["hits"]), 0)
        self.assertIn("Bangued", body["hits"][0]["municipality"])

    def test_search_validation(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.post("/v1/knowledge/search", json={"query": "", "limit": 5})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")


class TestAdminRoutes(unittest.TestCase):
    def test_index_status(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.get("/v1/index/status")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        names = {c["name"] for c in body["collections"]}
        self.assertEqual(
            names,
            {
                "prism_yield_records",
                "prism_yield_knowledge",
                "openstat_price_records",
                "openstat_price_knowledge",
                "agri_corpus_rag",
            },
        )

    def test_refresh_metadata(self) -> None:
        client, _ = make_client(seed_rows=sample_rows())
        resp = client.post("/v1/index/refresh-metadata")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["refreshed"])
        self.assertGreaterEqual(body["regions_count"], 1)


if __name__ == "__main__":
    unittest.main()
