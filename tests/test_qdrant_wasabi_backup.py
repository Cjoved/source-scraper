"""Tests for Qdrant Wasabi backup helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.storage import qdrant_wasabi_backup as qbackup


class QdrantWasabiBackupTests(unittest.TestCase):
    @mock.patch("src.storage.qdrant_wasabi_backup.rotate_and_upload")
    @mock.patch("src.storage.qdrant_wasabi_backup._download_snapshot_file")
    @mock.patch("src.storage.qdrant_wasabi_backup.get_s3_client")
    @mock.patch("src.storage.qdrant_wasabi_backup.wasabi_enabled", return_value=True)
    def test_backup_uploads_existing_collections(
        self,
        _enabled: mock.MagicMock,
        _s3: mock.MagicMock,
        mock_download: mock.MagicMock,
        mock_rotate: mock.MagicMock,
    ) -> None:
        client = mock.MagicMock()
        collection = mock.MagicMock()
        collection.name = "agri_corpus_rag"
        client.get_collections.return_value.collections = [collection]
        client.create_snapshot.return_value = mock.MagicMock(name="snap-1")

        def write_snapshot(collection_name: str, snapshot_name: str, dest: Path) -> None:
            dest.write_bytes(b"snapshot-bytes")

        mock_download.side_effect = write_snapshot
        mock_rotate.return_value = {"latest": "s3://bucket/key", "dated": "s3://bucket/dated", "snapshot_date": "2026-06-16"}

        with mock.patch.object(qbackup, "qdrant_collection_names", return_value=["agri_corpus_rag", "missing"]):
            uploads = qbackup.backup_qdrant_collections(
                log=lambda _m: None,
                qdrant_client=client,
                require_any=True,
            )

        self.assertEqual(len(uploads), 1)
        client.create_snapshot.assert_called_once_with(collection_name="agri_corpus_rag")
        mock_rotate.assert_called_once()
        self.assertEqual(mock_rotate.call_args.kwargs["kind"], "qdrant")


if __name__ == "__main__":
    unittest.main()
