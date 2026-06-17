"""Tests for Wasabi restore helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.storage import wasabi_restore as restore


class WasabiRestoreTests(unittest.TestCase):
    def test_restore_job_downloads_mapped_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_client = object()

            def fake_download(local_path: Path, **kwargs):
                local_path.parent.mkdir(parents=True, exist_ok=True)
                local_path.write_text("{}", encoding="utf-8")
                return {"local": str(local_path), "remote": "s3://bucket/key"}

            with (
                mock.patch.object(restore, "wasabi_enabled", return_value=True),
                mock.patch.object(restore, "get_s3_client", return_value=fake_client),
                mock.patch.object(restore, "download_latest", side_effect=fake_download),
                mock.patch("src.storage.wasabi_restore.data_path", side_effect=lambda *p: Path(tmp) / Path(*p)),
            ):
                results = restore.restore_job_artifacts("irri", log=lambda _m: None)
            self.assertEqual(len(results), 2)
            self.assertTrue((Path(tmp) / "irri_processed" / "irri_corpus.jsonl").is_file())
            self.assertTrue((Path(tmp) / "checkpoints" / "irri_checkpoint.json").is_file())


if __name__ == "__main__":
    unittest.main()
