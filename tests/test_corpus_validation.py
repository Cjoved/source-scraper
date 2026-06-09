"""Tests for post-job corpus validation wiring (P3.2)."""

from __future__ import annotations

import unittest
from unittest import mock
from unittest.mock import patch

from src.orchestrator.corpus_validation import (
    JOB_CORPUS_SOURCES,
    ValidationResult,
    validate_job_corpora,
    validate_quality_enabled,
)
from src.scripts.validate_corpus import FileReport


class CorpusValidationTests(unittest.TestCase):
    def test_pinoyrice_includes_pdfs_source(self) -> None:
        self.assertIn("pinoyrice_pdfs", JOB_CORPUS_SOURCES["pinoyrice"])

    @patch.dict("os.environ", {"ORCHESTRATOR_VALIDATE_QUALITY": "false"}, clear=False)
    def test_quality_toggle_off(self) -> None:
        self.assertFalse(validate_quality_enabled())

    @patch.dict("os.environ", {"ORCHESTRATOR_VALIDATE_QUALITY": "false"}, clear=False)
    @patch("src.orchestrator.corpus_validation.run_validation")
    def test_returns_validation_result(self, mock_run: mock.MagicMock) -> None:
        mock_run.return_value = (
            [
                FileReport(
                    source_id="philrice_news",
                    path="/tmp/x.jsonl",
                    status="ok",
                    records=1,
                )
            ],
            0,
        )
        result = validate_job_corpora("philrice_news", log=lambda _m: None)
        self.assertIsInstance(result, ValidationResult)
        self.assertTrue(result.passed)
        self.assertEqual(len(result.reports), 1)
        mock_run.assert_called_once()
        self.assertFalse(mock_run.call_args.kwargs["check_quality"])


if __name__ == "__main__":
    unittest.main()
