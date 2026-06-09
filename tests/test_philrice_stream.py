"""Tests for PhilRice stream processing helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.openstat.services import philrice as svc


class PhilRiceStreamTests(unittest.TestCase):
    def test_stream_enabled_default(self) -> None:
        with mock.patch.dict("os.environ", {"PHILRICE_STREAM_PROCESS": "true"}, clear=False):
            self.assertTrue(svc.stream_process_enabled())

    def test_delete_default_on_when_stream(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"PHILRICE_STREAM_PROCESS": "true", "PHILRICE_DELETE_PDF_AFTER_CLEAN": ""},
            clear=False,
        ):
            self.assertTrue(svc.delete_pdf_after_process())

    def test_ingest_appends_and_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "sample.pdf"
            pdf.write_bytes(b"%PDF-1.4 minimal")
            corpus = Path(tmp) / "corpus.jsonl"
            with mock.patch.object(svc, "process_one_pdf", return_value=[{"text": "x" * 120, "input": "x" * 120, "source": "philrice", "doc_id": "d1"}]):
                with mock.patch.object(svc, "delete_pdf_after_process", return_value=True):
                    with open(corpus, "w", encoding="utf-8") as fh:
                        n = svc.ingest_pdf_to_corpus(str(pdf), fh, delete_after=True)
            self.assertEqual(n, 1)
            self.assertFalse(pdf.exists())
            lines = corpus.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["source"], "philrice")


if __name__ == "__main__":
    unittest.main()
