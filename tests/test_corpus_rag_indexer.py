"""Tests for unified RAG corpus indexer (P3.8b/c)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.indexing.corpus_rag_indexer import (
    record_to_corpus_point,
    record_to_payload,
    run_corpus_rag_index,
)
from src.storage.qdrant_store import build_corpus_point_id
from tests.fakes.fake_store import FakeQdrantStore


class CorpusRecordMappingTests(unittest.TestCase):
    def test_build_corpus_point_id_stable(self) -> None:
        a = build_corpus_point_id("philrice", "doc-1")
        b = build_corpus_point_id("philrice", "doc-1")
        self.assertEqual(a, b)
        self.assertNotEqual(a, build_corpus_point_id("philrice", "doc-2"))

    def test_record_to_payload_skips_empty_text(self) -> None:
        self.assertIsNone(record_to_payload({"doc_id": "x", "text": "  "}, "philrice"))

    def test_record_to_corpus_point_maps_fields(self) -> None:
        record = {
            "text": "Rice farming guide " * 5,
            "doc_id": "doc-42",
            "url": "https://example.com",
            "title": "Guide",
            "filename": "guide.txt",
            "page": 3,
        }
        point = record_to_corpus_point(record, "philrice_news")
        self.assertIsNotNone(point)
        assert point is not None
        self.assertEqual(point.payload["source_id"], "philrice_news")
        self.assertEqual(point.payload["doc_id"], "doc-42")
        self.assertEqual(point.payload["page"], 3)


class CorpusRagIndexerRunTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, records: list[dict]) -> None:
        lines = [json.dumps(r, ensure_ascii=False) for r in records]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_dry_run_counts_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "philrice": root / "philrice.jsonl",
                "philrice_news": root / "news.jsonl",
                "pinoyrice": root / "pinoy.jsonl",
                "irri": root / "irri.jsonl",
            }
            rec = {
                "text": "sample corpus text " * 10,
                "input": "sample corpus text " * 10,
                "source": "test",
                "doc_id": "d1",
            }
            for p in paths.values():
                self._write_jsonl(p, [rec])

            from src.indexing import corpus_rag_indexer as indexer_mod

            original = indexer_mod.resolve_rag_sources

            def fake_resolve(*, source_filter: str | None = None):
                from src.indexing.corpus_manifest import RagCorpusSource

                specs = [
                    RagCorpusSource("philrice", "philrice.jsonl"),
                    RagCorpusSource("philrice_news", "news.jsonl"),
                    RagCorpusSource("pinoyrice", "pinoy.jsonl"),
                    RagCorpusSource("irri", "irri.jsonl"),
                ]
                if source_filter:
                    specs = [s for s in specs if s.source_id == source_filter]
                return [(s, root / s.relpath) for s in specs]

            indexer_mod.resolve_rag_sources = fake_resolve
            try:
                stats = run_corpus_rag_index(store=FakeQdrantStore(), dry_run=True)
            finally:
                indexer_mod.resolve_rag_sources = original

            self.assertEqual(stats.total_indexed, 4)
            self.assertEqual(stats.sources["philrice"].indexed, 1)

    def test_upsert_via_fake_store(self) -> None:
        store = FakeQdrantStore()
        point = record_to_corpus_point(
            {
                "text": "IRRI research on rice " * 5,
                "doc_id": "irri-1",
            },
            "irri",
        )
        assert point is not None
        count = store.upsert_corpus([point])
        self.assertEqual(count, 1)
        self.assertEqual(len(store.corpus), 1)


if __name__ == "__main__":
    unittest.main()
