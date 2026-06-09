"""Tests for orchestrator run context (P3.3/P3.4)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from src.orchestrator.config import JobSpec, OrchestratorConfig
from src.orchestrator.run_context import RunContext, make_run_id
from src.scripts.validate_corpus import FileReport


class RunContextTests(unittest.TestCase):
    def test_make_run_id(self) -> None:
        when = datetime(2026, 6, 4, 3, 5, 12, tzinfo=UTC)
        self.assertEqual(make_run_id("philrice_news", now=when), "20260604T030512Z_philrice_news")

    def test_manifest_and_validation_report_written(self) -> None:
        spec = JobSpec(
            id="philrice_news",
            enabled=True,
            cron="0 3 * * 0",
            browser_heavy=True,
            env_overrides={"PHILRICE_NEWS": "true"},
            timeout_minutes=180,
        )
        cfg = OrchestratorConfig(timezone="Asia/Manila", default_timeout_minutes=180, jobs=(spec,))
        when = datetime(2026, 6, 4, 3, 0, 0, tzinfo=UTC)

        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = Path(tmp) / "runs"
            with patch("src.orchestrator.run_context.RUNS_DIR", runs_dir):
                ctx = RunContext.start("philrice_news", spec, cfg, now=when)
                self.assertEqual(ctx.status, "running")
                self.assertTrue(ctx.manifest_path.is_file())

                rep = FileReport(
                    source_id="philrice_news",
                    path=str(Path(tmp) / "corpus.jsonl"),
                    status="ok",
                    records=3,
                )
                ctx.set_validation([rep], passed=True, check_quality=True)
                ctx.mark_ok()

                manifest = json.loads(ctx.manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], "ok")
                self.assertEqual(manifest["job_id"], "philrice_news")
                self.assertEqual(manifest["validation"]["passed"], True)
                self.assertEqual(len(manifest["outputs"]), 1)

                report = json.loads(ctx.validation_report_path.read_text(encoding="utf-8"))
                self.assertEqual(report["job_id"], "philrice_news")
                self.assertTrue(report["quality_checks"])
                self.assertEqual(report["files"][0]["records"], 3)


if __name__ == "__main__":
    unittest.main()
