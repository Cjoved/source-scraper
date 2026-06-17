"""Tests for IRRI stream processing helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.openstat.services import irri as svc


class IrriStreamTests(unittest.TestCase):
    def test_stream_enabled_default(self) -> None:
        with mock.patch.dict("os.environ", {"IRRI_STREAM_PROCESS": "true"}, clear=False):
            self.assertTrue(svc.stream_process_enabled())

    def test_delete_txt_default_on_when_stream(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"IRRI_STREAM_PROCESS": "true", "IRRI_DELETE_TXT_AFTER_PROCESS": ""},
            clear=False,
        ):
            self.assertTrue(svc.delete_txt_after_process())

    def test_ingest_txt_appends_and_deletes(self) -> None:
        body = "IRRI article body with enough characters for CPT minimum length. " * 5
        with tempfile.TemporaryDirectory() as tmp:
            txt = Path(tmp) / "sample.txt"
            txt.write_text(
                "URL: https://www.irri.org/news-and-events/news/sample\n"
                "Title: Sample Article | International Rice Research Institute\n\n"
                f"{body}",
                encoding="utf-8",
            )
            corpus = Path(tmp) / "corpus.jsonl"
            with open(corpus, "w", encoding="utf-8") as fh:
                with mock.patch.object(svc, "delete_txt_after_process", return_value=True):
                    n = svc.ingest_txt_to_corpus(str(txt), fh, delete_after=True)
            self.assertEqual(n, 1)
            self.assertFalse(txt.exists())
            lines = corpus.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["source"], "irri")


if __name__ == "__main__":
    unittest.main()
