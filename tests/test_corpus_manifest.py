"""Tests for RAG corpus manifest (P3.8a)."""

from __future__ import annotations

import unittest

from src.indexing.corpus_manifest import (
    RAG_CORPUS_SOURCES,
    RAG_SOURCE_BY_ID,
    resolve_rag_sources,
)


class CorpusManifestTests(unittest.TestCase):
    def test_rag_source_count(self) -> None:
        self.assertEqual(len(RAG_CORPUS_SOURCES), 5)

    def test_required_sources(self) -> None:
        required = {s.source_id for s in RAG_CORPUS_SOURCES if s.required}
        self.assertEqual(
            required,
            {"philrice", "philrice_news", "pinoyrice", "irri"},
        )

    def test_openstat_not_in_rag_manifest(self) -> None:
        ids = {s.source_id for s in RAG_CORPUS_SOURCES}
        self.assertNotIn("openstat", ids)

    def test_prism_browser_optional(self) -> None:
        spec = RAG_SOURCE_BY_ID["prism_browser"]
        self.assertFalse(spec.required)
        self.assertIn("prism_corpus_chunked.jsonl", spec.relpath)

    def test_resolve_all_sources(self) -> None:
        resolved = resolve_rag_sources()
        self.assertEqual(len(resolved), 5)
        ids = {spec.source_id for spec, _path in resolved}
        self.assertEqual(ids, set(RAG_SOURCE_BY_ID))

    def test_resolve_unknown_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_rag_sources(source_filter="not_a_source")


if __name__ == "__main__":
    unittest.main()
