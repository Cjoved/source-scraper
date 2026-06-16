"""Tests for POST /v1/corpus/search (P3.8d)."""

from __future__ import annotations

import unittest

from tests.helpers import make_client


def sample_corpus_rows() -> list[dict]:
    return [
        {
            "text": "PhilRice recommends hybrid rice seeds for wet season",
            "source_id": "philrice",
            "doc_id": "ph-1",
            "title": "Hybrid seeds",
        },
        {
            "text": "PinoyRice farmer tips on irrigation scheduling",
            "source_id": "pinoyrice",
            "doc_id": "pr-1",
        },
        {
            "text": "IRRI Philippines climate resilient varieties",
            "source_id": "irri",
            "doc_id": "ir-1",
            "url": "https://irri.org/example",
        },
    ]


class TestCorpusSearchRoute(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.fake = make_client()
        self.fake.seed_corpus(sample_corpus_rows())

    def test_search_returns_hits(self) -> None:
        resp = self.client.post(
            "/v1/corpus/search",
            json={"query": "hybrid rice seeds", "limit": 5},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertGreater(len(body["hits"]), 0)
        self.assertEqual(body["hits"][0]["source_id"], "philrice")
        self.assertIn("hybrid", body["hits"][0]["text"].lower())

    def test_search_source_ids_filter(self) -> None:
        resp = self.client.post(
            "/v1/corpus/search",
            json={
                "query": "rice",
                "limit": 10,
                "source_ids": ["irri"],
            },
        )
        self.assertEqual(resp.status_code, 200)
        hits = resp.json()["hits"]
        self.assertTrue(hits)
        self.assertTrue(all(h["source_id"] == "irri" for h in hits))

    def test_search_validation_empty_query(self) -> None:
        resp = self.client.post("/v1/corpus/search", json={"query": "", "limit": 5})
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["error"]["code"], "VALIDATION_ERROR")


if __name__ == "__main__":
    unittest.main()
