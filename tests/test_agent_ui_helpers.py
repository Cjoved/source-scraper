from __future__ import annotations

import unittest

from src.agent.ui_helpers import (
    apply_ui_command,
    build_agent_payload,
    format_agent_response,
    parse_source_ids,
    trim_history,
)


class AgentUiHelperTests(unittest.TestCase):
    def test_parse_source_ids_dedupes_and_clears(self) -> None:
        self.assertEqual(parse_source_ids("IRRI, philrice_news irri"), ["irri", "philrice_news"])
        self.assertIsNone(parse_source_ids("clear"))
        self.assertIsNone(parse_source_ids(""))

    def test_build_agent_payload_includes_optional_fields_and_trims_history(self) -> None:
        payload = build_agent_payload(
            message="  Ano ang latest news?  ",
            mode="chat",
            source_ids=["irri"],
            history=[
                {"role": "system", "content": "ignored"},
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
            crop="palay",
            language="taglish",
            max_tool_calls=2,
        )

        self.assertEqual(payload["message"], "Ano ang latest news?")
        self.assertEqual(payload["mode"], "chat")
        self.assertEqual(payload["source_ids"], ["irri"])
        self.assertEqual(payload["history"], [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}])
        self.assertEqual(payload["crop"], "palay")
        self.assertEqual(payload["language"], "taglish")
        self.assertEqual(payload["max_tool_calls"], 2)

    def test_trim_history_keeps_last_valid_messages(self) -> None:
        history = [{"role": "user", "content": f"message {idx}"} for idx in range(12)]

        trimmed = trim_history(history, limit=3)

        self.assertEqual([item["content"] for item in trimmed], ["message 9", "message 10", "message 11"])

    def test_trim_history_preserves_assistant_sources(self) -> None:
        history = [
            {"role": "user", "content": "latest news?"},
            {
                "role": "assistant",
                "content": "Narito ang listahan.",
                "sources": [
                    {
                        "source_id": "irri",
                        "title": "IRRI item",
                        "url": "https://example.test/irri",
                        "published_date": "2026-06-20",
                    }
                ],
            },
        ]

        trimmed = trim_history(history)

        self.assertEqual(len(trimmed), 2)
        self.assertEqual(trimmed[1]["sources"][0]["title"], "IRRI item")
        self.assertEqual(trimmed[1]["sources"][0]["published_date"], "2026-06-20")

    def test_apply_ui_command_updates_sources_without_api_call(self) -> None:
        result = apply_ui_command(
            "/sources irri,philrice_news",
            current_mode="chat",
            current_source_ids=None,
        )

        self.assertFalse(result.should_call_api)
        self.assertEqual(result.mode, "chat")
        self.assertEqual(result.source_ids, ["irri", "philrice_news"])
        self.assertIn("Source scope set", result.notice or "")

    def test_apply_ui_command_sources_multiline_sends_followup_query(self) -> None:
        result = apply_ui_command(
            "/sources philrice_news,irri\nMay bagong balita ba tungkol sa palay?",
            current_mode="chat",
            current_source_ids=None,
        )

        self.assertTrue(result.should_call_api)
        self.assertEqual(result.message, "May bagong balita ba tungkol sa palay?")
        self.assertEqual(result.mode, "chat")
        self.assertEqual(result.source_ids, ["philrice_news", "irri"])
        self.assertIsNone(result.notice)

    def test_apply_ui_command_sources_multiline_clear_sends_followup_query(self) -> None:
        result = apply_ui_command(
            "/sources clear\nMagkano ang palay ngayon?",
            current_mode="chat",
            current_source_ids=["irri"],
        )

        self.assertTrue(result.should_call_api)
        self.assertEqual(result.message, "Magkano ang palay ngayon?")
        self.assertIsNone(result.source_ids)

    def test_apply_ui_command_tasklist_with_message_calls_api(self) -> None:
        result = apply_ui_command(
            "/tasklist linisin ang corpus",
            current_mode="chat",
            current_source_ids=["irri"],
        )

        self.assertTrue(result.should_call_api)
        self.assertEqual(result.message, "linisin ang corpus")
        self.assertEqual(result.mode, "tasklist")
        self.assertEqual(result.source_ids, ["irri"])

    def test_format_agent_response_renders_structured_sections(self) -> None:
        markdown = format_agent_response(
            {
                "answer": "Average yield is 4.5 ton/ha.",
                "confidence": "high",
                "tasklist": [{"status": "pending", "task": "Review result."}],
                "sources": [
                    {
                        "source_id": "prism_yield_records",
                        "title": None,
                        "url": None,
                        "snippet": "Deterministic yield summary.",
                    }
                ],
                "tool_calls": [
                    {
                        "name": "summarize_yield",
                        "arguments": {"province": "Laguna"},
                        "summary": "Computed yield summary.",
                        "result_count": 1,
                    }
                ],
                "warnings": [{"code": "source_scope_ignored", "message": "Ignored source_ids."}],
                "took_ms": 12.34,
            }
        )

        self.assertIn("Average yield is 4.5 ton/ha.", markdown)
        self.assertIn("Agent response", markdown)
        self.assertIn("### Tasklist", markdown)
        self.assertIn("### Sources", markdown)
        self.assertIn("### Tool Trace", markdown)
        self.assertIn("### Warnings", markdown)
        self.assertIn("`high`", markdown)


    def test_build_agent_payload_includes_session_state(self) -> None:
        payload = build_agent_payload(
            message="Magkano ulit?",
            session_state={
                "location": "Nueva Ecija",
                "last_tool_name": "summarize_prices",
                "last_tool_args": {"geolocation": "Nueva Ecija"},
            },
        )

        self.assertEqual(payload["session_state"]["location"], "Nueva Ecija")
        self.assertEqual(payload["session_state"]["last_tool_name"], "summarize_prices")


if __name__ == "__main__":
    unittest.main()
