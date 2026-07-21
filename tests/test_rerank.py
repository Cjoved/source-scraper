"""Unit tests for local FlashRank helper (fail-open + ordering)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.services.rerank import (
    candidate_text,
    rerank_hit_payloads,
    rerank_texts,
    reset_ranker_for_tests,
)
from src.storage.qdrant_store import KnowledgeHitRecord


class TestRerank(unittest.TestCase):
    def setUp(self) -> None:
        reset_ranker_for_tests()

    def tearDown(self) -> None:
        reset_ranker_for_tests()

    def test_candidate_text_prefers_title_and_snippet(self) -> None:
        text = candidate_text(
            {"title": "IRRI news", "text": "Long body about rice farming research."}
        )
        self.assertIn("IRRI news", text)
        self.assertIn("Long body", text)

    def test_disabled_keeps_original_order(self) -> None:
        candidates = [
            {"text": "a", "score": 0.1},
            {"text": "b", "score": 0.9},
        ]
        result = rerank_texts("query", candidates, top_k=2, enabled=False)
        self.assertEqual(result.ordered_indexes, [0, 1])
        self.assertTrue(result.available)

    def test_fail_open_when_ranker_missing(self) -> None:
        with patch("src.services.rerank._get_ranker", return_value=None):
            result = rerank_texts(
                "query",
                [{"text": "first"}, {"text": "second"}],
                top_k=2,
                enabled=True,
            )
        self.assertEqual(result.ordered_indexes, [0, 1])
        self.assertFalse(result.available)
        self.assertIsNotNone(result.warning)

    def test_rerank_reorders_with_fake_ranker(self) -> None:
        fake_ranker = MagicMock()
        fake_ranker.rerank.return_value = [
            {"id": 1, "text": "second", "score": 0.95},
            {"id": 0, "text": "first", "score": 0.10},
        ]
        with patch("src.services.rerank._get_ranker", return_value=fake_ranker):
            with patch("flashrank.RerankRequest", MagicMock()):
                result = rerank_texts(
                    "rice news",
                    [{"text": "first", "score": 0.8}, {"text": "second", "score": 0.2}],
                    top_k=2,
                    enabled=True,
                )
        self.assertEqual(result.ordered_indexes, [1, 0])
        self.assertEqual(result.scores[0], 0.95)

    def test_rerank_hit_payloads_rebuilds_records(self) -> None:
        hits = [
            KnowledgeHitRecord(score=0.2, payload={"title": "Low", "text": "a"}),
            KnowledgeHitRecord(score=0.9, payload={"title": "High", "text": "b"}),
        ]
        fake_ranker = MagicMock()
        fake_ranker.rerank.return_value = [
            {"id": 0, "score": 0.99},
            {"id": 1, "score": 0.01},
        ]
        with patch("src.services.rerank._get_ranker", return_value=fake_ranker):
            with patch("flashrank.RerankRequest", MagicMock()):
                ordered, meta = rerank_hit_payloads("q", hits, top_k=2, enabled=True)
        self.assertEqual(ordered[0].payload["title"], "Low")
        self.assertGreaterEqual(ordered[0].score, ordered[1].score)
        self.assertTrue(meta.available)

    def test_latest_path_helper_not_required(self) -> None:
        # Smoke: empty candidates.
        result = rerank_texts("q", [], top_k=5, enabled=True)
        self.assertEqual(result.ordered_indexes, [])


if __name__ == "__main__":
    unittest.main()
