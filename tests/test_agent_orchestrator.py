from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import cast
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage

from src.agent.orchestrator import run_agent_chat
from src.api.schemas import AgentChatRequest, AgentMode
from src.api.settings import Settings
from tests.fakes.fake_store import FakeQdrantStore


@dataclass
class FakeMessage:
    content: object


class FakeModel:
    def __init__(self, content: object) -> None:
        self.content = content
        self.invocations: list[object] = []

    def invoke(self, input: object, config: object | None = None, **kwargs: object) -> FakeMessage:
        del config, kwargs
        self.invocations.append(input)
        return FakeMessage(self.content)


class TimeoutModel:
    def invoke(self, input: object, config: object | None = None, **kwargs: object) -> FakeMessage:
        del input, config, kwargs
        raise TimeoutError("provider timed out")


class ToolCallingModel:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.invocations: list[object] = []
        self.bound_tools: list[object] = []

    def bind_tools(self, tools: list[object]) -> "ToolCallingModel":
        self.bound_tools = tools
        return self

    def invoke(self, input: object, config: object | None = None, **kwargs: object) -> object:
        del config, kwargs
        self.invocations.append(input)
        return self.responses.pop(0)


def _settings(
    *,
    agent_provider: str = "deepseek",
    agent_api_key: str | None = "test-key",
    agent_model: str = "deepseek-chat",
) -> Settings:
    return Settings(
        agent_provider=agent_provider,
        agent_api_key=agent_api_key,
        agent_model=agent_model,
    )


class TestAgentOrchestrator(unittest.TestCase):
    def test_tasklist_model_response(self) -> None:
        model = FakeModel(
            """
            {
              "answer": "Narito ang tasklist.",
              "tasklist": [
                {"status": "pending", "task": "Review corpus sources."},
                {"status": "pending", "task": "Draft implementation steps."}
              ]
            }
            """
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="Gawan mo ng tasklist", mode=AgentMode.TASKLIST),
                _settings(),
            )

        self.assertEqual(response.answer, "Narito ang tasklist.")
        self.assertEqual(len(response.tasklist), 2)
        self.assertEqual(response.tasklist[0].task, "Review corpus sources.")
        self.assertEqual(response.warnings, [])
        self.assertEqual(len(model.invocations), 1)

    def test_chat_mode_drops_tasklist(self) -> None:
        model = FakeModel(
            '{"answer": "Okay, ready na ang chat mode.", "tasklist": [{"task": "Hidden"}]}'
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="Kamusta?", mode=AgentMode.CHAT),
                _settings(),
            )

        self.assertEqual(response.answer, "Okay, ready na ang chat mode.")
        self.assertEqual(response.tasklist, [])

    def test_missing_api_key_returns_fallback_warning(self) -> None:
        response = run_agent_chat(
            AgentChatRequest(message="Gawan mo ng tasklist", mode=AgentMode.TASKLIST),
            _settings(agent_api_key=None),
        )

        self.assertTrue(response.tasklist)
        self.assertEqual(response.warnings[0].code, "agent_api_key_missing")

    def test_plain_text_model_response_returns_warning(self) -> None:
        model = FakeModel("not json")
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="Gawan mo ng tasklist", mode=AgentMode.TASKLIST),
                _settings(),
            )

        self.assertEqual(response.answer, "not json")
        self.assertTrue(response.tasklist)
        self.assertEqual(response.warnings[0].code, "model_response_plain_text")

    def test_timeout_returns_specific_warning(self) -> None:
        with patch("src.agent.orchestrator.create_chat_model", return_value=TimeoutModel()):
            response = run_agent_chat(
                AgentChatRequest(message="Gawan mo ng tasklist", mode=AgentMode.TASKLIST),
                _settings(),
            )

        self.assertTrue(response.tasklist)
        self.assertEqual(response.warnings[0].code, "model_timeout")

    def test_tool_call_summarizes_yield_with_store(self) -> None:
        store = FakeQdrantStore()
        store.seed(
            [
                {
                    "year": 2020,
                    "semester_code": 1,
                    "region": "CAR",
                    "province": "Abra",
                    "municipality": "Bangued",
                    "avg_yield_ton_ha": 3.5,
                },
                {
                    "year": 2020,
                    "semester_code": 2,
                    "region": "CAR",
                    "province": "Abra",
                    "municipality": "Bangued",
                    "avg_yield_ton_ha": 4.5,
                },
            ]
        )
        model = ToolCallingModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "summarize_yield",
                            "args": {"province": "Abra", "year_min": 2020, "year_max": 2020},
                        }
                    ],
                ),
                FakeMessage('{"answer": "Average yield is 4.0 t/ha.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="average yield in Abra 2020", mode=AgentMode.CHAT),
                _settings(),
                store=store,
            )

        self.assertEqual(response.answer, "Average yield is 4.0 t/ha.")
        self.assertEqual(response.tool_calls[0].name, "summarize_yield")
        self.assertEqual(response.tool_calls[0].result_count, 2)
        self.assertEqual(response.sources[0].source_id, "prism_yield_records")
        self.assertEqual(len(model.bound_tools), 5)
        second_invocation = model.invocations[1]
        self.assertIsInstance(second_invocation, list)
        messages = cast(list[object], second_invocation)
        self.assertTrue(any(isinstance(message, ToolMessage) for message in messages))

    def test_tool_call_searches_corpus_with_sources(self) -> None:
        store = FakeQdrantStore()
        store.seed_corpus(
            [
                {
                    "source_id": "philrice_news",
                    "doc_id": "hybrid-seeds",
                    "title": "Hybrid seeds update",
                    "url": "https://example.test/hybrid",
                    "text": "PhilRice news about hybrid seeds and rice production.",
                }
            ]
        )
        model = ToolCallingModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "search_corpus",
                            "args": {"query": "PhilRice News about hybrid seeds", "limit": 5},
                        }
                    ],
                ),
                FakeMessage('{"answer": "Found one PhilRice News result about hybrid seeds.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="PhilRice News about hybrid seeds",
                    mode=AgentMode.CHAT,
                    source_ids=["philrice_news"],
                ),
                _settings(),
                store=store,
            )

        self.assertEqual(response.tool_calls[0].name, "search_corpus")
        self.assertEqual(response.tool_calls[0].result_count, 1)
        self.assertEqual(response.sources[0].source_id, "philrice_news")
        self.assertEqual(response.sources[0].title, "Hybrid seeds update")

    def test_tool_call_summarizes_prices_with_store(self) -> None:
        store = FakeQdrantStore()
        store.seed_prices(
            [
                {
                    "geolocation": "Abra",
                    "commodity_type": "Palay and Rice",
                    "commodity": "Palay",
                    "year": 2024,
                    "month": "January",
                    "price_php_per_kg": 22.0,
                },
                {
                    "geolocation": "Abra",
                    "commodity_type": "Palay and Rice",
                    "commodity": "Palay",
                    "year": 2024,
                    "month": "February",
                    "price_php_per_kg": 24.0,
                },
            ]
        )
        model = ToolCallingModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "summarize_prices",
                            "args": {
                                "geolocation": "Abra",
                                "commodity": "Palay",
                                "year_min": 2024,
                                "year_max": 2024,
                            },
                        }
                    ],
                ),
                FakeMessage('{"answer": "Average palay price is PHP 23.00/kg.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="OpenSTAT palay price in Abra 2024", mode=AgentMode.CHAT),
                _settings(),
                store=store,
            )

        self.assertEqual(response.answer, "Average palay price is PHP 23.00/kg.")
        self.assertEqual(response.tool_calls[0].name, "summarize_prices")
        self.assertEqual(response.tool_calls[0].result_count, 2)
        self.assertEqual(response.sources[0].source_id, "openstat_price_records")


if __name__ == "__main__":
    unittest.main()
