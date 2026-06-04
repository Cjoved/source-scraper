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
from src.orchestrator.jobs import JOB_ORDER, run_all, run_job, validate_config
from src.orchestrator.lock import browser_job_lock, lock_holder, lock_path_for_tests
from src.orchestrator.preflight import ensure_flaresolverr, is_flaresolverr_healthy
from src.orchestrator.schedule import job_due_now
from src.services.config import PROJECT_ROOT


class OrchestratorConfigTests(unittest.TestCase):
    def test_load_default_yaml_has_seven_jobs(self) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertEqual(cfg.timezone, "Asia/Manila")
        self.assertEqual(len(cfg.jobs), 7)
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


class RunJobTests(unittest.TestCase):
    @patch.dict("src.orchestrator.jobs._RUNNERS", {"philrice": mock.MagicMock()}, clear=False)
    def test_run_job_success(self) -> None:
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
        self.assertEqual(called_ids, list(JOB_ORDER))


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
    @patch("src.orchestrator.jobs.ensure_flaresolverr", return_value=False)
    def test_openstat_fails_when_flaresolverr_down(self, _mock_ensure: mock.MagicMock) -> None:
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertFalse(run_job("openstat", cfg))

    @patch("src.orchestrator.jobs.ensure_flaresolverr", return_value=True)
    @patch.dict(
        "src.orchestrator.jobs._RUNNERS",
        {"openstat": mock.MagicMock()},
        clear=False,
    )
    def test_openstat_runs_when_flaresolverr_up(self, _mock_ensure: mock.MagicMock) -> None:
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

    @patch("src.orchestrator.jobs.lock_holder")
    @patch.dict("src.orchestrator.jobs._RUNNERS", {"philrice": mock.MagicMock()}, clear=False)
    def test_run_job_skips_when_browser_lock_held(self, mock_holder: mock.MagicMock) -> None:
        from src.orchestrator import jobs

        mock_holder.return_value = {"pid": 12345, "job_id": "irri"}
        cfg = load_config(PROJECT_ROOT / "orchestrator.yaml")
        self.assertTrue(run_job("philrice", cfg))
        jobs._RUNNERS["philrice"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
