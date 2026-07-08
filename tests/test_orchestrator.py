"""Tests for orchestrator config, schedule, and job dispatch."""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime
from unittest import mock
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.orchestrator.config import load_config
from src.orchestrator.corpus_validation import ValidationResult
from src.orchestrator.jobs import JOB_ORDER, run_all, run_job, validate_config
from src.orchestrator.lock import browser_job_lock, lock_holder, lock_path_for_tests
from src.orchestrator.preflight import ensure_flaresolverr, ensure_qdrant, is_flaresolverr_healthy, is_qdrant_healthy
from src.orchestrator.schedule import job_due_now
from src.services.config import PROJECT_ROOT


class OrchestratorConfigTests(unittest.TestCase):
    def test_load_default_yaml_has_twelve_jobs(self) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertEqual(cfg.timezone, "Asia/Manila")
        self.assertEqual(len(cfg.jobs), 12)
        ids = {j.id for j in cfg.jobs}
        self.assertEqual(ids, set(JOB_ORDER))

    def test_validate_config_matches_registry(self) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        validate_config(cfg)


class ScheduleTests(unittest.TestCase):
    def test_philrice_due_sunday_0200_ph(self) -> None:
        tz = ZoneInfo("Asia/Manila")
        # 2026-05-31 is a Sunday
        when = datetime(2026, 5, 31, 2, 0, tzinfo=tz)
        self.assertTrue(job_due_now("0 2 * * 0", "Asia/Manila", now=when))

    def test_philrice_not_due_monday(self) -> None:
        tz = ZoneInfo("Asia/Manila")
        when = datetime(2026, 6, 1, 2, 0, tzinfo=tz)
        self.assertFalse(job_due_now("0 2 * * 0", "Asia/Manila", now=when))


def _validation_ok() -> ValidationResult:
    return ValidationResult(passed=True, reports=(), sources_checked=(), warnings=())


def _validation_fail() -> ValidationResult:
    return ValidationResult(passed=False, reports=(), sources_checked=(), warnings=())


class RunJobTests(unittest.TestCase):
    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs.validate_job_corpora", return_value=_validation_ok())
    @patch.dict("src.orchestrator.jobs._RUNNERS", {"philrice": mock.MagicMock()}, clear=False)
    def test_run_job_success(
        self,
        _mock_validate: mock.MagicMock,
        _mock_alert: mock.MagicMock,
    ) -> None:
        from src.orchestrator import jobs

        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertTrue(run_job("philrice", cfg))
        jobs._RUNNERS["philrice"].assert_called_once()

    def test_run_job_unknown_id(self) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertFalse(run_job("not_a_job", cfg))

    @patch("src.orchestrator.jobs.run_job", return_value=True)
    def test_run_all_order(self, mock_run_job: mock.MagicMock) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        code = run_all(cfg)
        self.assertEqual(code, 0)
        called_ids = [call.args[0] for call in mock_run_job.call_args_list]
        enabled_order = [
            job_id
            for job_id in JOB_ORDER
            if (spec := cfg.job_by_id(job_id)) is not None and spec.enabled
        ]
        self.assertEqual(called_ids, enabled_order)

    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.agent.error_explainer.explain_run_failure")
    @patch.dict(
        "src.orchestrator.jobs._RUNNERS",
        {"prism_yield": mock.MagicMock(side_effect=RuntimeError("boom"))},
        clear=False,
    )
    def test_run_job_attaches_error_explanation_before_alert(
        self,
        mock_explain: mock.MagicMock,
        mock_alert: mock.MagicMock,
    ) -> None:
        from src.agent.error_explainer import ErrorExplanation

        mock_explain.return_value = ErrorExplanation(
            summary="The scraper crashed.",
            likely_cause="Runtime error during the job.",
            suggested_actions=["Inspect manifest", "Retry after fixing the cause"],
            generated_by="ai",
            model="deepseek-chat",
        )

        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertFalse(run_job("prism_yield", cfg))

        mock_alert.assert_called_once()
        alert_ctx = mock_alert.call_args.args[0]
        self.assertIsNotNone(alert_ctx.error_explanation)
        self.assertEqual(alert_ctx.error_explanation["summary"], "The scraper crashed.")
        self.assertEqual(alert_ctx.error_explanation["generated_by"], "ai")


class CliParserTests(unittest.TestCase):
    def test_run_mutually_exclusive(self) -> None:
        from src.orchestrator.cli import build_parser

        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["run", "philrice", "--all"])

    def test_serve_subcommand(self) -> None:
        from src.orchestrator.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["serve", "--interval", "30"])
        self.assertEqual(args.command, "serve")
        self.assertEqual(args.interval, 30)

    def test_test_alerts_subcommand(self) -> None:
        from src.orchestrator.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["test-alerts"])
        self.assertEqual(args.command, "test-alerts")


class BrowserLockTests(unittest.TestCase):
    def setUp(self) -> None:
        lock_path = lock_path_for_tests()
        if lock_path.is_file():
            lock_path.unlink()

    def tearDown(self) -> None:
        lock_path = lock_path_for_tests()
        if lock_path.is_file():
            lock_path.unlink()

    def test_acquire_and_release(self) -> None:
        with browser_job_lock("philrice") as acquired:
            self.assertTrue(acquired)
            holder = lock_holder()
            self.assertIsNotNone(holder)
            self.assertEqual(holder["job_id"], "philrice")
            self.assertEqual(holder["pid"], os.getpid())
        self.assertIsNone(lock_holder())

    def test_stale_lock_cleared(self) -> None:
        lock_path = lock_path_for_tests()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(
            json.dumps({"pid": 999999999, "job_id": "old", "started_at": "2020-01-01T00:00:00"}),
            encoding="utf-8",
        )
        self.assertIsNone(lock_holder())
        self.assertFalse(lock_path.is_file())

    def test_second_job_skips_when_lock_held(self) -> None:
        with browser_job_lock("philrice") as first:
            self.assertTrue(first)
            with browser_job_lock("irri") as second:
                self.assertFalse(second)


class PreflightTests(unittest.TestCase):
    @patch("src.orchestrator.preflight.requests.post")
    def test_is_flaresolverr_healthy_ok(self, mock_post: mock.MagicMock) -> None:
        mock_post.return_value.raise_for_status = mock.MagicMock()
        mock_post.return_value.json.return_value = {"status": "ok"}
        self.assertTrue(is_flaresolverr_healthy())

    @patch(
        "src.orchestrator.preflight.requests.post",
        side_effect=__import__("requests").RequestException("connection refused"),
    )
    def test_is_flaresolverr_healthy_down(self, _mock_post: mock.MagicMock) -> None:
        self.assertFalse(is_flaresolverr_healthy())

    @patch("src.orchestrator.preflight.is_flaresolverr_healthy", return_value=True)
    def test_ensure_flaresolverr_already_up(self, _mock_health: mock.MagicMock) -> None:
        self.assertTrue(ensure_flaresolverr(start_if_down=False))

    @patch("src.orchestrator.preflight._start_flaresolverr_compose", return_value=False)
    @patch("src.orchestrator.preflight.is_flaresolverr_healthy", return_value=False)
    def test_ensure_flaresolverr_start_fails(
        self, _mock_health: mock.MagicMock, _mock_start: mock.MagicMock
    ) -> None:
        self.assertFalse(ensure_flaresolverr(log=lambda _m: None))


class OpenstatPreflightJobTests(unittest.TestCase):
    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs._attach_error_explanation")
    @patch("src.orchestrator.jobs.ensure_flaresolverr", return_value=False)
    def test_openstat_fails_when_flaresolverr_down(
        self,
        _mock_ensure: mock.MagicMock,
        _mock_explain: mock.MagicMock,
        _mock_alert: mock.MagicMock,
    ) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertFalse(run_job("openstat", cfg))

    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs.validate_job_corpora", return_value=_validation_ok())
    @patch("src.orchestrator.jobs.ensure_flaresolverr", return_value=True)
    @patch.dict(
        "src.orchestrator.jobs._RUNNERS",
        {"openstat": mock.MagicMock()},
        clear=False,
    )
    def test_openstat_runs_when_flaresolverr_up(
        self,
        _mock_ensure: mock.MagicMock,
        _mock_validate: mock.MagicMock,
        _mock_alert: mock.MagicMock,
    ) -> None:
        from src.orchestrator import jobs

        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertTrue(run_job("openstat", cfg))
        jobs._RUNNERS["openstat"].assert_called_once()


class BrowserLockJobTests(unittest.TestCase):
    def setUp(self) -> None:
        lock_path = lock_path_for_tests()
        if lock_path.is_file():
            lock_path.unlink()

    def tearDown(self) -> None:
        lock_path = lock_path_for_tests()
        if lock_path.is_file():
            lock_path.unlink()

    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs.lock_holder")
    @patch.dict("src.orchestrator.jobs._RUNNERS", {"philrice": mock.MagicMock()}, clear=False)
    def test_run_job_skips_when_browser_lock_held(
        self,
        mock_holder: mock.MagicMock,
        _mock_alert: mock.MagicMock,
    ) -> None:
        from src.orchestrator import jobs

        mock_holder.return_value = {"pid": 12345, "job_id": "irri"}
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertTrue(run_job("philrice", cfg))
        jobs._RUNNERS["philrice"].assert_not_called()


class CorpusValidationHookTests(unittest.TestCase):
    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs._attach_error_explanation")
    @patch("src.orchestrator.jobs.validate_job_corpora", return_value=_validation_fail())
    @patch.dict("src.orchestrator.jobs._RUNNERS", {"philrice": mock.MagicMock()}, clear=False)
    def test_run_job_fails_when_corpus_invalid(
        self,
        mock_validate: mock.MagicMock,
        _mock_explain: mock.MagicMock,
        _mock_alert: mock.MagicMock,
    ) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertFalse(run_job("philrice", cfg))
        mock_validate.assert_called_once()
        self.assertEqual(mock_validate.call_args.args[0], "philrice")

    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs.validate_job_corpora", return_value=_validation_ok())
    @patch.dict("src.orchestrator.jobs._RUNNERS", {"prism_yield": mock.MagicMock()}, clear=False)
    def test_prism_yield_skips_corpus_validation(
        self,
        mock_validate: mock.MagicMock,
        _mock_alert: mock.MagicMock,
    ) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertTrue(run_job("prism_yield", cfg))
        mock_validate.assert_not_called()


class CorpusRagIndexJobTests(unittest.TestCase):
    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs._attach_error_explanation")
    @patch("src.orchestrator.jobs.ensure_qdrant", return_value=False)
    def test_corpus_rag_index_fails_when_qdrant_down(
        self,
        _mock_ensure: mock.MagicMock,
        _mock_explain: mock.MagicMock,
        _mock_alert: mock.MagicMock,
    ) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertFalse(run_job("corpus_rag_index", cfg))

    @patch("src.storage.wasabi_store.wasabi_enabled", return_value=False)
    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs.ensure_qdrant", return_value=True)
    @patch.dict(
        "src.orchestrator.jobs._RUNNERS",
        {"corpus_rag_index": mock.MagicMock()},
        clear=False,
    )
    def test_corpus_rag_index_runs_when_qdrant_up(
        self,
        _mock_ensure: mock.MagicMock,
        _mock_alert: mock.MagicMock,
        _mock_wasabi: mock.MagicMock,
    ) -> None:
        from src.indexing.corpus_rag_indexer import CorpusIndexStats, SourceIndexStats
        from src.orchestrator import jobs

        jobs._RUNNERS["corpus_rag_index"].return_value = CorpusIndexStats(
            sources={"philrice": SourceIndexStats(read=1, indexed=1)}
        )
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertTrue(run_job("corpus_rag_index", cfg))
        jobs._RUNNERS["corpus_rag_index"].assert_called_once()


class OpenstatIndexJobTests(unittest.TestCase):
    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs._attach_error_explanation")
    @patch("src.orchestrator.jobs.ensure_qdrant", return_value=False)
    def test_openstat_index_fails_when_qdrant_down(
        self,
        _mock_ensure: mock.MagicMock,
        _mock_explain: mock.MagicMock,
        _mock_alert: mock.MagicMock,
    ) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertFalse(run_job("openstat_index", cfg))

    @patch("src.storage.wasabi_store.wasabi_enabled", return_value=False)
    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs.ensure_qdrant", return_value=True)
    @patch.dict(
        "src.orchestrator.jobs._RUNNERS",
        {"openstat_index": mock.MagicMock()},
        clear=False,
    )
    def test_openstat_index_runs_when_qdrant_up(
        self,
        _mock_ensure: mock.MagicMock,
        _mock_alert: mock.MagicMock,
        _mock_wasabi: mock.MagicMock,
    ) -> None:
        from src.indexing.price_indexer import PriceIndexStats
        from src.orchestrator import jobs

        jobs._RUNNERS["openstat_index"].return_value = PriceIndexStats(
            rows_seen=10, records_upserted=10, knowledge_upserted=10
        )
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertTrue(run_job("openstat_index", cfg))
        jobs._RUNNERS["openstat_index"].assert_called_once()


class PrismIndexJobTests(unittest.TestCase):
    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs._attach_error_explanation")
    @patch("src.orchestrator.jobs.ensure_qdrant", return_value=False)
    def test_prism_index_fails_when_qdrant_down(
        self,
        _mock_ensure: mock.MagicMock,
        _mock_explain: mock.MagicMock,
        _mock_alert: mock.MagicMock,
    ) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertFalse(run_job("prism_index", cfg))

    @patch("src.storage.wasabi_store.wasabi_enabled", return_value=False)
    @patch("src.orchestrator.jobs.send_run_alert")
    @patch("src.orchestrator.jobs.ensure_qdrant", return_value=True)
    @patch.dict(
        "src.orchestrator.jobs._RUNNERS",
        {"prism_index": mock.MagicMock()},
        clear=False,
    )
    def test_prism_index_runs_when_qdrant_up(
        self,
        _mock_ensure: mock.MagicMock,
        _mock_alert: mock.MagicMock,
        _mock_wasabi: mock.MagicMock,
    ) -> None:
        from src.orchestrator import jobs

        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertTrue(run_job("prism_index", cfg))
        jobs._RUNNERS["prism_index"].assert_called_once()


class QdrantPreflightTests(unittest.TestCase):
    @patch("src.orchestrator.preflight.requests.get")
    def test_is_qdrant_healthy_ok(self, mock_get: mock.MagicMock) -> None:
        mock_get.return_value.status_code = 200
        self.assertTrue(is_qdrant_healthy())

    @patch(
        "src.orchestrator.preflight.requests.get",
        side_effect=__import__("requests").RequestException("down"),
    )
    def test_is_qdrant_healthy_down(self, _mock_get: mock.MagicMock) -> None:
        self.assertFalse(is_qdrant_healthy())

    @patch("src.orchestrator.preflight.is_qdrant_healthy", return_value=True)
    def test_ensure_qdrant_already_up(self, _mock_health: mock.MagicMock) -> None:
        self.assertTrue(ensure_qdrant(start_if_down=False))

    @patch("src.orchestrator.preflight.subprocess.run")
    @patch("src.orchestrator.preflight.is_qdrant_healthy", return_value=False)
    def test_ensure_qdrant_down_does_not_start_compose(
        self,
        _mock_health: mock.MagicMock,
        mock_run: mock.MagicMock,
    ) -> None:
        logs: list[str] = []

        self.assertFalse(ensure_qdrant(log=logs.append))
        mock_run.assert_not_called()
        self.assertTrue(any("external to this compose stack" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
