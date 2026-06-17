"""Tests for PinoyRice stream processing helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.openstat.services import pinoyrice as svc


class PinoyRiceStreamTests(unittest.TestCase):
    def test_stream_enabled_default(self) -> None:
        with mock.patch.dict("os.environ", {"PINOYRICE_STREAM_PROCESS": "true"}, clear=False):
            self.assertTrue(svc.stream_process_enabled())

    def test_delete_pdf_default_on_when_stream(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"PINOYRICE_STREAM_PROCESS": "true", "PINOYRICE_DELETE_PDF_AFTER_CLEAN": ""},
            clear=False,
        ):
            self.assertTrue(svc.delete_pdf_after_process())

    def test_ingest_record_writes_cpt(self) -> None:
        text = "PinoyRice farming guidance with enough content for CPT minimum chars. " * 5
        record = {
            "text": text,
            "url": "https://www.pinoyrice.com/the-rice-plant/",
            "title": "The Rice Plant",
            "doc_id": "the_rice_plant",
        }
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "corpus.jsonl"
            with open(corpus, "w", encoding="utf-8") as fh:
                n = svc.ingest_record_to_corpus(record, fh)
            self.assertGreaterEqual(n, 1)
            row = json.loads(corpus.read_text(encoding="utf-8").strip())
            self.assertEqual(row["source"], "pinoyrice")
            self.assertEqual(row["url"], record["url"])

    def test_ingest_pdf_deletes_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "handout.pdf"
            pdf.write_bytes(b"%PDF-1.4 minimal")
            corpus = Path(tmp) / "corpus.jsonl"
            with mock.patch.object(
                svc,
                "process_one_pdf",
                return_value=[{"text": "x" * 120, "input": "x" * 120, "source": "pinoyrice", "doc_id": "d1"}],
            ):
                with mock.patch.object(svc, "delete_pdf_after_process", return_value=True):
                    with open(corpus, "w", encoding="utf-8") as fh:
                        n = svc.ingest_pdf_to_corpus(str(pdf), fh, delete_after=True)
            self.assertEqual(n, 1)
            self.assertFalse(pdf.exists())


if __name__ == "__main__":
    unittest.main()
