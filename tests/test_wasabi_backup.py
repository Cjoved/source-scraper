"""Tests for Wasabi per-job backup helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.orchestrator.wasabi_backup import JOB_WASABI_ARTIFACTS, backup_job_artifacts
from src.storage.wasabi_store import object_key, rotate_and_upload, wasabi_enabled


class WasabiStoreTests(unittest.TestCase):
    def test_object_key_matches_bucket_layout(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "WASABI_ACCESS_KEY": "key",
                "WASABI_SECRET_KEY": "secret",
                "WASABI_BUCKET": "agent-scraper",
                "WASABI_CORPUS_PREFIX": "corpus-data/",
                "WASABI_CHECKPOINT_PREFIX": "Checkpoint/",
            },
            clear=False,
        ):
            self.assertEqual(
                object_key("corpus", "latest", "irri_corpus.jsonl"),
                "corpus-data/latest/irri_corpus.jsonl",
            )
            self.assertEqual(
                object_key("checkpoint", "backup", "irri_checkpoint.json"),
                "Checkpoint/backup/irri_checkpoint.json",
            )
            self.assertEqual(
                object_key("corpus", "dated", "irri_corpus.jsonl", snapshot_date="2026-06-16"),
                "corpus-data/history/2026-06-16/irri_corpus.jsonl",
            )
            self.assertEqual(
                object_key("qdrant", "latest", "agri_corpus_rag.snapshot"),
                "qdrant-data/latest/agri_corpus_rag.snapshot",
            )

    def test_rotate_and_upload_copies_uploads_and_dated_snapshot(self) -> None:
        client = mock.MagicMock()
        client.exceptions = mock.MagicMock()

        def head_object(**_kwargs: object) -> None:
            return None

        client.head_object.side_effect = head_object
        client.get_paginator.return_value.paginate.return_value = [{"Contents": []}]

        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "irri_corpus.jsonl"
            local.write_text('{"text":"x"}\n', encoding="utf-8")
            with mock.patch.dict(
                "os.environ",
                {
                    "WASABI_ACCESS_KEY": "key",
                    "WASABI_SECRET_KEY": "secret",
                    "WASABI_DATED_RETENTION": "2",
                },
                clear=False,
            ), mock.patch("src.storage.wasabi_store._object_exists", return_value=True):
                result = rotate_and_upload(
                    local,
                    kind="corpus",
                    remote_filename="irri_corpus.jsonl",
                    client=client,
                    snapshot_date="2026-06-16",
                )
            client.copy_object.assert_called_once()
            self.assertEqual(client.upload_file.call_count, 2)
            self.assertIn("corpus-data/latest/irri_corpus.jsonl", result["latest"])
            self.assertIn("corpus-data/history/2026-06-16/irri_corpus.jsonl", result["dated"])
            self.assertEqual(result["snapshot_date"], "2026-06-16")

    def test_prune_dated_history_keeps_two(self) -> None:
        from src.storage.wasabi_store import _prune_dated_history

        client = mock.MagicMock()
        client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "corpus-data/history/2026-06-01/irri_corpus.jsonl"},
                    {"Key": "corpus-data/history/2026-06-08/irri_corpus.jsonl"},
                    {"Key": "corpus-data/history/2026-06-15/irri_corpus.jsonl"},
                ]
            }
        ]
        with mock.patch.dict(
            "os.environ",
            {"WASABI_ACCESS_KEY": "key", "WASABI_SECRET_KEY": "secret", "WASABI_DATED_RETENTION": "2"},
            clear=False,
        ):
            deleted = _prune_dated_history(
                client, "agent-scraper", "corpus", "irri_corpus.jsonl", retention=2
            )
        self.assertEqual(deleted, ["corpus-data/history/2026-06-01/irri_corpus.jsonl"])
        client.delete_object.assert_called_once()

    def test_wasabi_disabled_without_credentials(self) -> None:
        with mock.patch.dict("os.environ", {"WASABI_ENABLED": "false"}, clear=False):
            self.assertFalse(wasabi_enabled())


class WasabiBackupMappingTests(unittest.TestCase):
    def test_scrape_jobs_have_corpus_and_checkpoint(self) -> None:
        for job_id in ("irri", "pinoyrice", "philrice", "philrice_news"):
            artifacts = JOB_WASABI_ARTIFACTS[job_id]
            kinds = {a.kind for a in artifacts}
            self.assertIn("corpus", kinds)
            self.assertIn("checkpoint", kinds)

    @mock.patch("src.orchestrator.wasabi_backup.rotate_and_upload")
    @mock.patch("src.orchestrator.wasabi_backup.get_s3_client")
    @mock.patch("src.orchestrator.wasabi_backup.wasabi_enabled", return_value=True)
    @mock.patch("src.orchestrator.wasabi_backup.data_path")
    def test_backup_job_skips_missing_optional_files(
        self,
        mock_data_path: mock.MagicMock,
        _enabled: mock.MagicMock,
        _client: mock.MagicMock,
        mock_rotate: mock.MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "irri_corpus.jsonl"
            corpus.write_text('{"text":"sample"}\n', encoding="utf-8")
            ck = root / "irri_checkpoint.json"
            ck.write_text("{}", encoding="utf-8")

            def resolve(*parts: str) -> Path:
                if parts == ("irri_processed", "irri_corpus.jsonl"):
                    return corpus
                if parts == ("checkpoints", "irri_checkpoint.json"):
                    return ck
                return root / Path(*parts)

            mock_data_path.side_effect = resolve
            mock_rotate.return_value = {"latest": "s3://bucket/key"}

            uploads = backup_job_artifacts("irri", log=lambda _m: None)
            self.assertEqual(len(uploads), 2)
            self.assertEqual(mock_rotate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
