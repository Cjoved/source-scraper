"""Tests for PhilRice News stream processing helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.openstat.services import philrice_news as svc


class PhilriceNewsStreamTests(unittest.TestCase):
    def test_stream_enabled_default(self) -> None:
        with mock.patch.dict("os.environ", {"PHILRICE_NEWS_STREAM_PROCESS": "true"}, clear=False):
            self.assertTrue(svc.stream_process_enabled())

    def test_delete_txt_default_on_when_stream(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"PHILRICE_NEWS_STREAM_PROCESS": "true", "PHILRICE_NEWS_DELETE_TXT_AFTER_PROCESS": ""},
            clear=False,
        ):
            self.assertTrue(svc.delete_txt_after_process())

    def test_article_to_cpt_includes_url_and_title(self) -> None:
        body = "PhilRice news article body with enough characters for CPT minimum length. " * 5
        records = svc.article_to_cpt_records(
            "https://www.philrice.gov.ph/sample-article/",
            "Sample Headline",
            body,
            "Sample Headline_2026-03-11.txt",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["url"], "https://www.philrice.gov.ph/sample-article/")
        self.assertEqual(records[0]["title"], "Sample Headline")
        self.assertEqual(records[0]["source"], "philrice_news")

    def test_ingest_txt_appends_and_deletes(self) -> None:
        body = "Legacy PhilRice news body with enough characters for CPT minimum length. " * 5
        with tempfile.TemporaryDirectory() as tmp:
            txt = Path(tmp) / "Sample Headline_2026-03-11.txt"
            txt.write_text(body, encoding="utf-8")
            corpus = Path(tmp) / "corpus.jsonl"
            with open(corpus, "w", encoding="utf-8") as fh:
                with mock.patch.object(svc, "delete_txt_after_process", return_value=True):
                    n = svc.ingest_txt_to_corpus(
                        str(txt),
                        fh,
                        url="https://www.philrice.gov.ph/sample/",
                        title="Sample Headline",
                        delete_after=True,
                    )
            self.assertEqual(n, 1)
            self.assertFalse(txt.exists())
            row = json.loads(corpus.read_text(encoding="utf-8").strip())
            self.assertEqual(row["title"], "Sample Headline")
            self.assertEqual(row["url"], "https://www.philrice.gov.ph/sample/")

    def test_run_leftovers_uses_checkpoint_maps(self) -> None:
        body = "Leftover article body with enough characters for CPT minimum length. " * 5
        with tempfile.TemporaryDirectory() as tmp:
            news = Path(tmp) / "news"
            news.mkdir()
            fname = "Old headline_2026-01-01.txt"
            (news / fname).write_text(body, encoding="utf-8")
            corpus_path = Path(tmp) / "out" / "philrice_news_corpus.jsonl"

            with (
                mock.patch.object(svc, "PHILRICE_NEWS_DIR", str(news)),
                mock.patch.object(svc, "PHILRICE_NEWS_PROCESSED_DIR", str(corpus_path.parent)),
                mock.patch.object(svc, "OUTPUT_JSONL", str(corpus_path)),
                mock.patch.object(svc, "delete_txt_after_process", return_value=True),
            ):
                total = svc.run_leftovers(
                    url_to_file={"https://www.philrice.gov.ph/old/": fname},
                    url_to_title={"https://www.philrice.gov.ph/old/": "Old headline"},
                )
            self.assertEqual(total, 1)
            self.assertFalse((news / fname).exists())
            row = json.loads(corpus_path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["url"], "https://www.philrice.gov.ph/old/")


if __name__ == "__main__":
    unittest.main()
