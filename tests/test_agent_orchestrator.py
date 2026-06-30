from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from datetime import date
from typing import cast
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage

from src.agent.orchestrator import run_agent_chat
from src.agent.query_planner import resolve_date_range
from src.api.schemas import AgentChatRequest, AgentConfidence, AgentMode
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


def _messages_text(messages: object) -> str:
    if not isinstance(messages, list):
        return str(messages)
    return "\n".join(str(getattr(message, "content", message)) for message in messages)


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
    def test_relative_date_resolver_handles_years_ago(self) -> None:
        resolved = resolve_date_range(
            "Ano ang average farmgate price ng palay sa Nueva Ecija 3 years ago?",
            today=date(2026, 6, 24),
        )

        self.assertEqual(resolved.year_min, 2023)
        self.assertEqual(resolved.year_max, 2023)

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
        self.assertEqual(response.confidence, AgentConfidence.LOW)

    def test_missing_api_key_returns_fallback_warning(self) -> None:
        response = run_agent_chat(
            AgentChatRequest(message="Gawan mo ng tasklist", mode=AgentMode.TASKLIST),
            _settings(agent_api_key=None),
        )

        self.assertTrue(response.tasklist)
        self.assertEqual(response.warnings[0].code, "agent_api_key_missing")
        self.assertEqual(response.confidence, AgentConfidence.LOW)

    def test_farmer_price_query_without_location_adds_clarification_context(self) -> None:
        model = FakeModel(
            '{"answer": "Para mas tama ang presyo, kailangan ko muna ang lugar. Saang province o lugar mo gustong tingnan ang presyo?", "tasklist": []}'
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="Magkano palay ngayon?", mode=AgentMode.CHAT),
                _settings(),
            )

        prompt_text = _messages_text(model.invocations[0])
        self.assertIn("intent=price_query", prompt_text)
        self.assertIn("missing_context=True", prompt_text)
        self.assertIn("Saang province o lugar mo gustong tingnan ang presyo?", prompt_text)
        self.assertIn("Saang province", response.answer)

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
        self.assertEqual(response.confidence, AgentConfidence.HIGH)
        self.assertEqual(len(model.bound_tools), 5)
        second_invocation = model.invocations[1]
        self.assertIsInstance(second_invocation, list)
        messages = cast(list[object], second_invocation)
        self.assertTrue(any(isinstance(message, ToolMessage) for message in messages))

    def test_farmer_yield_context_injects_location_default(self) -> None:
        store = FakeQdrantStore()
        store.seed(
            [
                {
                    "year": 2023,
                    "semester_code": 1,
                    "region": "Region II",
                    "province": "Isabela",
                    "municipality": "Ilagan",
                    "avg_yield_ton_ha": 5.0,
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
                            "name": "summarize_yield",
                            "args": {"year_min": 2023, "year_max": 2023},
                        }
                    ],
                ),
                FakeMessage('{"answer": "Average yield is 5.0 t/ha.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="Kumusta ani noong 2023?",
                    mode=AgentMode.CHAT,
                    location="Isabela",
                ),
                _settings(),
                store=store,
            )

        self.assertEqual(response.tool_calls[0].arguments["province"], "Isabela")
        self.assertEqual(response.tool_calls[0].result_count, 1)
        self.assertEqual(response.confidence, AgentConfidence.HIGH)

    def test_duplicate_tool_calls_are_cached_and_not_repeated_in_trace(self) -> None:
        store = FakeQdrantStore()
        store.seed(
            [
                {
                    "year": 2024,
                    "semester_code": 1,
                    "region": "CALABARZON",
                    "province": "Laguna",
                    "municipality": "Bay",
                    "avg_yield_ton_ha": 4.5,
                }
            ]
        )
        repeated_call = {
            "id": "call_1",
            "name": "summarize_yield",
            "args": {"province": "Laguna", "year_min": 2024, "year_max": 2024},
        }
        model = ToolCallingModel(
            [
                AIMessage(content="", tool_calls=[repeated_call]),
                AIMessage(content="", tool_calls=[{**repeated_call, "id": "call_2"}]),
                FakeMessage('{"answer": "May matching yield data sa Laguna.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="Ano ang yield average sa Laguna 2 years ago?",
                    mode=AgentMode.CHAT,
                ),
                _settings(),
                store=store,
            )

        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.tool_calls[0].name, "summarize_yield")
        self.assertEqual(response.tool_calls[0].result_count, 1)
        self.assertFalse(any(warning.code == "tool_limit_reached" for warning in response.warnings))
        self.assertEqual(response.confidence, AgentConfidence.HIGH)

    def test_tool_limit_after_valid_data_returns_tool_backed_answer(self) -> None:
        store = FakeQdrantStore()
        store.seed(
            [
                {
                    "year": 2024,
                    "semester_code": 1,
                    "region": "CALABARZON",
                    "province": "Laguna",
                    "municipality": "Bay",
                    "avg_yield_ton_ha": 4.5,
                }
            ]
        )
        calls = [
            {
                "id": f"call_{idx}",
                "name": "summarize_yield" if idx <= 4 else "search_yield_knowledge",
                "args": {"province": "Laguna", "year_min": 2024, "year_max": 2024}
                if idx <= 4
                else {"query": "yield Laguna", "province": "Laguna", "year_min": 2024, "year_max": 2024},
            }
            for idx in range(1, 6)
        ]
        model = ToolCallingModel([AIMessage(content="", tool_calls=calls)])

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="Ano ang yield average sa Laguna 2 years ago?",
                    mode=AgentMode.CHAT,
                    max_tool_calls=1,
                ),
                _settings(),
                store=store,
            )

        self.assertNotIn("Agent route is available", response.answer)
        self.assertTrue(response.tool_calls)
        self.assertTrue(response.sources)
        self.assertTrue(any(warning.code == "tool_limit_reached" for warning in response.warnings))
        self.assertEqual(response.confidence, AgentConfidence.HIGH)

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
        self.assertEqual(response.confidence, AgentConfidence.MEDIUM)

    def test_latest_corpus_request_injects_scope_and_latest_sort(self) -> None:
        store = FakeQdrantStore()
        store.seed_corpus(
            [
                {
                    "source_id": "irri",
                    "doc_id": "older",
                    "title": "Older IRRI news",
                    "url": "https://example.test/older",
                    "filename": "older_irri_news_2024-01-15.txt",
                    "text": "IRRI rice news about farmers.",
                },
                {
                    "source_id": "irri",
                    "doc_id": "pdf-page",
                    "title": "Gender inclusive legislative framework laws women resilience",
                    "url": "https://example.test/report.pdf",
                    "filename": "legal_report_2026-06-15.pdf",
                    "page": 83,
                    "text": "Gender-Sensitive Disaster Risk Management and Action on Climate Change.",
                },
                {
                    "source_id": "irri",
                    "doc_id": "newer",
                    "title": "Latest IRRI news",
                    "url": "https://example.test/newer",
                    "filename": "latest_irri_news_2026-05-20.txt",
                    "text": "Newly published article from the International Rice Research Institute.",
                },
                {
                    "source_id": "philrice_news",
                    "doc_id": "philrice",
                    "title": "PhilRice news",
                    "url": "https://example.test/philrice",
                    "filename": "philrice_news_2026-06-01.txt",
                    "text": "IRRI rice news about farmers.",
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
                            "name": "search_corpus",
                            "args": {"query": "IRRI rice news", "limit": 2},
                        }
                    ],
                ),
                FakeMessage('{"answer": "Latest IRRI news: Latest IRRI news.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="ano ang latest news sa irri?",
                    mode=AgentMode.CHAT,
                    source_ids=["irri"],
                ),
                _settings(),
                store=store,
            )

        self.assertEqual(response.tool_calls[0].arguments["source_ids"], ["irri"])
        self.assertEqual(response.tool_calls[0].arguments["sort_by"], "latest")
        self.assertEqual(response.confidence, AgentConfidence.MEDIUM)
        second_invocation = cast(list[object], model.invocations[1])
        tool_message = next(message for message in second_invocation if isinstance(message, ToolMessage))
        tool_payload = json.loads(str(tool_message.content))
        hits = tool_payload["payload"]["hits"]
        self.assertEqual(hits[0]["title"], "Latest IRRI news")
        self.assertNotIn("Gender inclusive", {hit["title"] for hit in hits})
        self.assertTrue(all(hit["source_id"] == "irri" for hit in hits))

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
        self.assertEqual(response.confidence, AgentConfidence.HIGH)

    def test_farmer_price_context_injects_location_and_crop_defaults(self) -> None:
        store = FakeQdrantStore()
        store.seed_prices(
            [
                {
                    "geolocation": "Nueva Ecija",
                    "commodity_type": "Palay and Rice",
                    "commodity": "Palay",
                    "year": 2024,
                    "month": "January",
                    "price_php_per_kg": 25.0,
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
                            "name": "summarize_prices",
                            "args": {"year_min": 2024, "year_max": 2024},
                        }
                    ],
                ),
                FakeMessage('{"answer": "Average palay price is PHP 25.00/kg.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="Magkano palay noong 2024?",
                    mode=AgentMode.CHAT,
                    location="Nueva Ecija",
                    crop="palay",
                ),
                _settings(),
                store=store,
            )

        self.assertEqual(response.tool_calls[0].arguments["geolocation"], "Nueva Ecija")
        self.assertEqual(response.tool_calls[0].arguments["commodity"], "Palay")
        self.assertEqual(response.tool_calls[0].result_count, 1)
        self.assertEqual(response.confidence, AgentConfidence.HIGH)

    def test_price_query_plan_resolves_relative_date_and_ignores_corpus_sources(self) -> None:
        expected_year = date.today().year - 3
        store = FakeQdrantStore()
        store.seed_prices(
            [
                {
                    "geolocation": "Nueva Ecija",
                    "commodity_type": "Palay and Rice",
                    "commodity": "Palay",
                    "year": expected_year,
                    "month": "January",
                    "price_php_per_kg": 25.0,
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
                            "name": "summarize_prices",
                            "args": {
                                "geolocation": "Wrong Place",
                                "commodity": "Rice",
                                "year_min": 2022,
                                "year_max": 2022,
                            },
                        }
                    ],
                ),
                FakeMessage('{"answer": "Average palay price is PHP 25.00/kg.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="Ano ang average farmgate price ng palay sa Nueva Ecija 3 years ago?",
                    mode=AgentMode.CHAT,
                    source_ids=["philrice_news", "irri"],
                ),
                _settings(),
                store=store,
            )

        self.assertEqual(response.tool_calls[0].arguments["geolocation"], "Nueva Ecija")
        self.assertEqual(response.tool_calls[0].arguments["commodity"], "Palay")
        self.assertEqual(response.tool_calls[0].arguments["year_min"], expected_year)
        self.assertEqual(response.tool_calls[0].arguments["year_max"], expected_year)
        self.assertTrue(any(warning.code == "source_scope_ignored" for warning in response.warnings))
        self.assertEqual(response.sources[0].source_id, "openstat_price_records")
        self.assertEqual(response.confidence, AgentConfidence.HIGH)

    def test_farmer_news_query_defaults_to_farmer_corpus_sources(self) -> None:
        store = FakeQdrantStore()
        store.seed_corpus(
            [
                {
                    "source_id": "philrice_news",
                    "doc_id": "news",
                    "title": "Palay update",
                    "url": "https://example.test/news",
                    "filename": "palay_update_2026-01-01.txt",
                    "text": "Palay update for farmers.",
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
                            "args": {"query": "latest balita sa palay", "limit": 3},
                        }
                    ],
                ),
                FakeMessage('{"answer": "May nakita akong palay update.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="May latest balita ba sa palay?", mode=AgentMode.CHAT),
                _settings(),
                store=store,
            )

        self.assertEqual(
            response.tool_calls[0].arguments["source_ids"],
            ["philrice_news", "irri"],
        )
        self.assertEqual(response.tool_calls[0].arguments["sort_by"], "latest")
        self.assertEqual(response.confidence, AgentConfidence.MEDIUM)

    def test_latest_papers_query_defaults_to_publication_sources(self) -> None:
        store = FakeQdrantStore()
        store.seed_corpus(
            [
                {
                    "source_id": "irri",
                    "doc_id": "irri-news",
                    "title": "Latest IRRI news",
                    "filename": "irri_news_2026-06-20.txt",
                    "text": "Latest news but not a paper source.",
                },
                {
                    "source_id": "philrice",
                    "doc_id": "philrice-paper",
                    "title": "PhilRice rice production paper",
                    "filename": "philrice_paper_2026-06-01.pdf",
                    "text": "Research paper about rice production.",
                },
                {
                    "source_id": "pinoyrice",
                    "doc_id": "pinoyrice-guide",
                    "title": "PinoyRice production guide",
                    "filename": "pinoyrice_publication_2026-05-15.pdf",
                    "text": "Farmer publication about palay production.",
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
                            "name": "search_corpus",
                            "args": {"query": "latest papers", "limit": 5},
                        }
                    ],
                ),
                FakeMessage('{"answer": "May latest papers mula PhilRice at PinoyRice.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="Ano yung latest papers na meron tayo?", mode=AgentMode.CHAT),
                _settings(),
                store=store,
            )

        self.assertEqual(response.tool_calls[0].arguments["source_ids"], ["philrice", "pinoyrice"])
        self.assertEqual(response.tool_calls[0].arguments["sort_by"], "latest")
        second_invocation = cast(list[object], model.invocations[1])
        tool_message = next(message for message in second_invocation if isinstance(message, ToolMessage))
        tool_payload = json.loads(str(tool_message.content))
        hits = tool_payload["payload"]["hits"]
        self.assertEqual({hit["source_id"] for hit in hits}, {"philrice", "pinoyrice"})
        self.assertNotIn("irri", {source.source_id for source in response.sources})

    def test_farmer_advisory_without_crop_adds_one_clarification_context(self) -> None:
        model = FakeModel(
            '{"answer": "Pwede kitang tulungan. Palay ba ito, at anong stage na ng tanim?", "tasklist": []}'
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="May sakit yung dahon, ano gagawin?", mode=AgentMode.CHAT),
                _settings(),
            )

        prompt_text = _messages_text(model.invocations[0])
        self.assertIn("intent=advisory_query", prompt_text)
        self.assertIn("missing_context=True", prompt_text)
        self.assertIn("Palay ba ito, at anong stage na ng tanim?", prompt_text)
        self.assertIn("Palay ba ito", response.answer)

    def test_empty_tool_results_add_no_results_warning_and_low_confidence(self) -> None:
        store = FakeQdrantStore()
        model = ToolCallingModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "search_corpus",
                            "args": {"query": "nonexistent news", "limit": 5},
                        }
                    ],
                ),
                FakeMessage('{"answer": "No matching data found from search_corpus.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="Find nonexistent news", mode=AgentMode.CHAT),
                _settings(),
                store=store,
            )

        self.assertEqual(response.tool_calls[0].name, "search_corpus")
        self.assertEqual(response.tool_calls[0].result_count, 0)
        self.assertEqual(response.sources, [])
        self.assertEqual(response.confidence, AgentConfidence.LOW)
        self.assertTrue(any(warning.code == "no_results" for warning in response.warnings))

    def test_zero_row_summary_does_not_return_evidence_source(self) -> None:
        store = FakeQdrantStore()
        model = ToolCallingModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_1",
                            "name": "summarize_prices",
                            "args": {
                                "geolocation": "Nueva Ecija",
                                "commodity": "Palay",
                                "year_min": 2023,
                                "year_max": 2023,
                            },
                        }
                    ],
                ),
                FakeMessage('{"answer": "No matching data found from summarize_prices.", "tasklist": []}'),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="Presyo ng palay sa Nueva Ecija noong 2023", mode=AgentMode.CHAT),
                _settings(),
                store=store,
            )

        self.assertEqual(response.tool_calls[0].name, "summarize_prices")
        self.assertEqual(response.tool_calls[0].result_count, 0)
        self.assertEqual(response.sources, [])
        self.assertTrue(any(warning.code == "no_results" for warning in response.warnings))

    def test_price_query_blocks_irrelevant_corpus_fallback_sources(self) -> None:
        store = FakeQdrantStore()
        store.seed_corpus(
            [
                {
                    "source_id": "irri",
                    "doc_id": "climate-1",
                    "title": "Climate advisory",
                    "text": "palay climate advisory but not a farmgate price record",
                    "published_date": "2026-06-01",
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
                            "name": "summarize_prices",
                            "args": {"geolocation": "Abra", "commodity": "Palay"},
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_2",
                            "name": "search_prices",
                            "args": {
                                "query": "palay presyo Abra",
                                "geolocation": "Abra",
                                "commodity": "Palay",
                            },
                        }
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_3",
                            "name": "search_corpus",
                            "args": {
                                "query": "presyo ng palay Abra 2025",
                                "sort_by": "latest",
                            },
                        }
                    ],
                ),
                FakeMessage(
                    '{"answer": "Wala akong matching OpenSTAT price record for palay sa Abra.", "tasklist": []}'
                ),
            ]
        )

        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(message="Magkano palay ngayon dito sa Abra?", mode=AgentMode.CHAT),
                _settings(),
                store=store,
            )

        self.assertEqual([call.name for call in response.tool_calls], ["summarize_prices", "search_prices"])
        self.assertEqual(response.sources, [])
        self.assertEqual(response.confidence, AgentConfidence.LOW)
        self.assertTrue(any(warning.code == "tool_scope_blocked" for warning in response.warnings))
        self.assertTrue(any(warning.code == "no_results" for warning in response.warnings))


if __name__ == "__main__":
    unittest.main()
