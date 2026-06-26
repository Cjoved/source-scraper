"""Tests for orchestrator failure alerts (P3.6)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from src.orchestrator.alerts import (
    _alert_message,
    _alert_message_html,
    _build_discord_payload,
    _resolve_severity_theme,
    _should_alert,
    alert_on_success,
    alerts_enabled,
    send_run_alert,
    send_test_alerts,
)
from src.scripts.validate_corpus import FileReport
from src.orchestrator.config import JobSpec, OrchestratorConfig
from src.orchestrator.run_context import RunContext


def _failed_ctx() -> RunContext:
    spec = JobSpec(
        id="philrice",
        enabled=True,
        cron="0 2 * * 0",
        browser_heavy=True,
        env_overrides={},
        timeout_minutes=180,
    )
    cfg = OrchestratorConfig(timezone="Asia/Manila", default_timeout_minutes=180, jobs=(spec,))
    when = datetime(2026, 6, 4, 2, 0, 0, tzinfo=UTC)
    with patch("src.orchestrator.run_context.RUNS_DIR"):
        ctx = RunContext.start("philrice", spec, cfg, now=when)
    ctx.mark_failed(message="test failure", error_type="TestError")
    return ctx


class AlertsTests(unittest.TestCase):
    @patch.dict("os.environ", {"ALERT_ENABLED": "false"}, clear=False)
    def test_no_op_when_disabled(self) -> None:
        self.assertFalse(alerts_enabled())
        self.assertEqual(send_run_alert(_failed_ctx()), [])

    @patch.dict(
        "os.environ",
        {"ALERT_ENABLED": "true", "ALERT_LOCAL_FILE": "true"},
        clear=False,
    )
    def test_local_file_alert(self) -> None:
        ctx = _failed_ctx()
        with tempfile.TemporaryDirectory() as tmp:
            alerts_dir = Path(tmp)
            with patch("src.orchestrator.alerts.ALERTS_DIR", alerts_dir):
                sent = send_run_alert(ctx)
            self.assertIn("local_file", sent)
            latest = alerts_dir / "last_failure.json"
            self.assertTrue(latest.is_file())
            data = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(data["job_id"], "philrice")

    @patch.dict(
        "os.environ",
        {
            "ALERT_ENABLED": "true",
            "ALERT_LOCAL_FILE": "false",
            "ALERT_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test",
            "ALERT_TELEGRAM_BOT_TOKEN": "",
            "ALERT_WEBHOOK_URL": "",
            "ALERT_SLACK_WEBHOOK_URL": "",
        },
        clear=False,
    )
    @patch("src.orchestrator.alerts._post_json")
    def test_discord_sent(self, mock_post: mock.MagicMock) -> None:
        sent = send_run_alert(_failed_ctx())
        self.assertIn("discord", sent)
        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args[0][1]
        self.assertIn("embeds", payload)
        self.assertEqual(payload["embeds"][0]["color"], 0x5865F2)

    def test_discord_embed_clean_layout(self) -> None:
        embed = _build_discord_payload(_failed_ctx())["embeds"][0]
        self.assertIn("Agent Scraper", embed["footer"]["text"])
        self.assertIn("⏱ Duration", embed["fields"][0]["name"])
        names = [f["name"] for f in embed["fields"]]
        self.assertEqual(sum(1 for n in names if "Duration" in n), 1)
        self.assertIn("📄 Manifest", names)

    @patch.dict(
        "os.environ",
        {
            "ALERT_ENABLED": "true",
            "ALERT_LOCAL_FILE": "false",
            "ALERT_TELEGRAM_BOT_TOKEN": "token",
            "ALERT_TELEGRAM_CHAT_ID": "123",
            "ALERT_DISCORD_WEBHOOK_URL": "",
            "ALERT_WEBHOOK_URL": "",
            "ALERT_SLACK_WEBHOOK_URL": "",
        },
        clear=False,
    )
    @patch("src.orchestrator.alerts._post_json")
    def test_telegram_sent(self, mock_post: mock.MagicMock) -> None:
        sent = send_run_alert(_failed_ctx())
        self.assertIn("telegram", sent)
        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args[0][1]
        self.assertEqual(payload.get("parse_mode"), "HTML")
        text = payload.get("text", "")
        self.assertIn("Agent Scraper", text)
        self.assertIn("PhilRice", text)

    def test_alert_message_includes_brand_and_agent(self) -> None:
        html = _alert_message_html(_failed_ctx())
        self.assertIn("Agent Scraper", html)
        self.assertIn("🌾 PhilRice", html)
        self.assertIn("uv run python -m src.orchestrator run philrice", html)
        self.assertIn("data/runs/", html)
        self.assertNotIn("What happened", html)

    def test_severity_theme_colors(self) -> None:
        ctx = _failed_ctx()
        self.assertIn("🔵", _resolve_severity_theme(ctx).badge)
        ctx.mark_failed(message="boom", error_type="JobError")
        self.assertIn("🔴", _resolve_severity_theme(ctx).badge)
        ctx.mark_failed(message="bad corpus", error_type="ValidationError")
        self.assertIn("🟠", _resolve_severity_theme(ctx).badge)

    def test_success_theme(self) -> None:
        ctx = _failed_ctx()
        ctx.set_validation(
            [FileReport(source_id="philrice", path="data/x.jsonl", status="ok", records=10)],
            passed=True,
        )
        ctx.mark_ok()
        self.assertIn("🟢", _resolve_severity_theme(ctx).badge)
        html = _alert_message_html(ctx)
        self.assertIn("completed successfully", html)
        self.assertNotIn("What happened", html)

    @patch.dict("os.environ", {"ALERT_ON_SUCCESS": "true"}, clear=False)
    def test_should_alert_on_success_when_enabled(self) -> None:
        self.assertTrue(alert_on_success())
        ctx = _failed_ctx()
        ctx.mark_ok()
        self.assertTrue(_should_alert(ctx))

    @patch.dict("os.environ", {"ALERT_ON_WARNING": "true"}, clear=False)
    def test_should_alert_on_warning_when_enabled(self) -> None:
        ctx = _failed_ctx()
        ctx.mark_ok()
        ctx.add_warning("quality threshold borderline")
        self.assertTrue(_should_alert(ctx))

    @patch.dict("os.environ", {"ALERT_ENABLED": "true", "ALERT_LOCAL_FILE": "false"}, clear=False)
    @patch("src.orchestrator.alerts._post_json")
    def test_send_test_alerts_failure_is_red(self, mock_post: mock.MagicMock) -> None:
        with patch.dict(
            "os.environ",
            {
                "ALERT_TELEGRAM_BOT_TOKEN": "token",
                "ALERT_TELEGRAM_CHAT_ID": "123",
            },
            clear=False,
        ):
            send_test_alerts(job_id="philrice", kind="failure")
        telegram_payloads = [
            call[0][1]
            for call in mock_post.call_args_list
            if isinstance(call[0][1], dict) and "text" in call[0][1]
        ]
        self.assertTrue(telegram_payloads, "expected at least one Telegram payload")
        text = telegram_payloads[0]["text"]
        self.assertIn("JOB FAILED", text)
        self.assertNotIn("TEST ALERT", text)
        self.assertIn("AI explanation", text)
        self.assertIn("sample AI explanation", text)

    def test_alert_includes_traceback_tail(self) -> None:
        ctx = _failed_ctx()
        try:
            raise RuntimeError("disk full on corpus write")
        except RuntimeError as exc:
            ctx.mark_failed(message=str(exc), exc=exc)
        html = _alert_message_html(ctx)
        self.assertIn("RuntimeError", html)
        self.assertIn("disk full", html)

    def test_plain_alert_message_includes_brand(self) -> None:
        text = _alert_message(_failed_ctx())
        self.assertIn("Agent Scraper", text)
        self.assertIn("🌾 PhilRice", text)
        self.assertIn("🔁", text)

    def test_alerts_include_error_explanation(self) -> None:
        ctx = _failed_ctx()
        ctx.set_error_explanation(
            {
                "summary": "Hindi maabot ang source site.",
                "likely_cause": "Temporary network or anti-bot service issue.",
                "suggested_actions": ["Check service health", "Retry the orchestrator job"],
                "generated_by": "ai",
                "model": "deepseek-chat",
            }
        )

        text = _alert_message(ctx)
        self.assertIn("AI explanation", text)
        self.assertIn("Hindi maabot ang source site", text)
        self.assertIn("Retry the orchestrator job", text)

        embed = _build_discord_payload(ctx)["embeds"][0]
        fields = embed["fields"]
        names = [field["name"] for field in fields]
        self.assertIn("🧠 AI Explanation", names)


if __name__ == "__main__":
    unittest.main()
