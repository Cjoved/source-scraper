"""Tests for AI-assisted scraper error explanations."""

from __future__ import annotations

import unittest

from src.agent.error_explainer import ErrorSnapshot, explain_error
from src.api.settings import Settings


class _Response:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeModel:
    def __init__(self, content: str) -> None:
        self.content = content

    def invoke(self, _messages: object) -> _Response:
        return _Response(self.content)


def _settings() -> Settings:
    return Settings(
        agent_enabled=True,
        agent_provider="deepseek",
        agent_api_key="test-key",
        agent_model="deepseek-chat",
    )


class ErrorExplainerTests(unittest.TestCase):
    def test_fallback_explains_qdrant_preflight(self) -> None:
        explanation = explain_error(
            ErrorSnapshot(
                job_id="corpus_rag_index",
                run_id="run-1",
                error_type="PreflightError",
                message="Qdrant preflight failed — indexer cannot run.",
            ),
            settings=Settings(agent_enabled=False),
        )

        self.assertEqual(explanation.generated_by, "fallback")
        self.assertIn("Qdrant", explanation.summary)
        self.assertTrue(any("QDRANT_URL" in action for action in explanation.suggested_actions))

    def test_ai_json_response_is_parsed(self) -> None:
        content = (
            '{"summary":"Hindi mabasa ang source site.",'
            '"likely_cause":"Temporary network failure.",'
            '"suggested_actions":["Check network","Retry the job"]}'
        )

        explanation = explain_error(
            ErrorSnapshot(
                job_id="philrice_news",
                run_id="run-2",
                error_type="RuntimeError",
                message="read timed out",
            ),
            settings=_settings(),
            model_factory=lambda _settings: _FakeModel(content),
        )

        self.assertEqual(explanation.generated_by, "ai")
        self.assertEqual(explanation.summary, "Hindi mabasa ang source site.")
        self.assertEqual(explanation.suggested_actions[0], "Check network")

    def test_bad_ai_output_uses_fallback(self) -> None:
        explanation = explain_error(
            ErrorSnapshot(
                job_id="openstat",
                run_id="run-3",
                error_type="JobError",
                message="not json",
            ),
            settings=_settings(),
            model_factory=lambda _settings: _FakeModel("plain text"),
        )

        self.assertEqual(explanation.generated_by, "fallback")
        self.assertIn("AI explanation fallback used", explanation.warning or "")


if __name__ == "__main__":
    unittest.main()
