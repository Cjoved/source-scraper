"""Unit tests for the dedicated search plan agent."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.agent.intent import infer_farmer_intent
from src.agent.orchestrator import run_agent_chat
from src.agent.plan_agent import (
    build_search_plan,
    deterministic_corpus_query,
    merge_corpus_results_rrf,
)
from src.agent.query_planner import build_query_plan
from src.agent.tools import ToolExecutionResult
from src.api.schemas import AgentChatRequest, AgentMode, AgentSource
from tests.fakes.fake_store import FakeQdrantStore
from tests.test_agent_orchestrator import FakeMessage, ToolCallingModel, _settings
from unittest.mock import patch
from langchain_core.messages import AIMessage


class TestPlanAgent(unittest.TestCase):
    def test_deterministic_corpus_query_strips_taglish_filler(self) -> None:
        farmer = infer_farmer_intent(
            message="Ano ang latest agri news ngayon?",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=None,
        )
        plan = build_query_plan(
            message="Ano ang latest agri news ngayon?",
            farmer_context=farmer,
            source_ids=None,
        )
        query = deterministic_corpus_query(
            "Ano ang latest agri news ngayon?",
            query_plan=plan,
            farmer_context=farmer,
        )
        self.assertNotEqual(query.lower(), "ano ang latest agri news ngayon?")
        self.assertIn("latest", query.lower())
        self.assertTrue("news" in query.lower() or "agriculture" in query.lower())

    def test_news_plan_forces_search_corpus_with_rewritten_query(self) -> None:
        farmer = infer_farmer_intent(
            message="Ano ang latest agri news ngayon?",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=["irri"],
        )
        query_plan = build_query_plan(
            message="Ano ang latest agri news ngayon?",
            farmer_context=farmer,
            source_ids=["irri"],
        )
        search_plan = build_search_plan(
            message="Ano ang latest agri news ngayon?",
            farmer_context=farmer,
            query_plan=query_plan,
            plan_rewrite=False,
        )
        self.assertEqual(search_plan.tool_name, "search_corpus")
        self.assertFalse(search_plan.skip_retrieval)
        self.assertEqual(search_plan.tool_args.get("sort_by"), "latest")
        self.assertEqual(search_plan.tool_args.get("source_ids"), ["irri"])
        self.assertNotEqual(
            search_plan.tool_args.get("query", "").lower(),
            "ano ang latest agri news ngayon?",
        )
        self.assertIn("IRRI", search_plan.tool_args.get("query", ""))

    def test_price_plan_forces_summarize_prices(self) -> None:
        farmer = infer_farmer_intent(
            message="Magkano ang average farmgate price ng mais sa Nueva Ecija?",
            user_type="farmer",
            location="Nueva Ecija",
            crop="mais",
            language=None,
            source_ids=None,
        )
        query_plan = build_query_plan(
            message="Magkano ang average farmgate price ng mais sa Nueva Ecija?",
            farmer_context=farmer,
            source_ids=["irri"],
        )
        search_plan = build_search_plan(
            message="Magkano ang average farmgate price ng mais sa Nueva Ecija?",
            farmer_context=farmer,
            query_plan=query_plan,
            plan_rewrite=False,
        )
        self.assertEqual(search_plan.tool_name, "summarize_prices")
        self.assertEqual(search_plan.tool_args.get("geolocation"), "Nueva Ecija")
        self.assertEqual(search_plan.tool_args.get("commodity"), "Corn")
        self.assertIsNone(search_plan.source_ids)

    def test_metadata_plan_forces_list_openstat_commodities(self) -> None:
        farmer = infer_farmer_intent(
            message="Ano pa ang crops na available sa data?",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=None,
        )
        query_plan = build_query_plan(
            message="Ano pa ang crops na available sa data?",
            farmer_context=farmer,
            source_ids=None,
        )
        search_plan = build_search_plan(
            message="Ano pa ang crops na available sa data?",
            farmer_context=farmer,
            query_plan=query_plan,
            plan_rewrite=False,
        )
        self.assertEqual(farmer.intent, "metadata_query")
        self.assertEqual(search_plan.tool_name, "list_openstat_commodities")
        self.assertFalse(search_plan.skip_retrieval)

    def test_list_openstat_commodities_tool_returns_catalog(self) -> None:
        from src.agent.tools import ToolExecutionContext, _list_openstat_commodities_impl
        from src.api.price_metadata_cache import build_price_snapshot_from_rows

        store = FakeQdrantStore()
        rows = [
            {
                "geolocation": "Abra",
                "commodity_type": "Cereals",
                "commodity": "Palay",
                "year": 2023,
                "month": "August",
                "price_php_per_kg": 24.0,
                "source": "openstat_psa",
                "text": "Palay price",
            },
            {
                "geolocation": "Abra",
                "commodity_type": "Cereals",
                "commodity": "Corn [White]",
                "year": 2023,
                "month": "August",
                "price_php_per_kg": 18.0,
                "source": "openstat_psa",
                "text": "Corn price",
            },
            {
                "geolocation": "Abra",
                "commodity_type": "Livestock",
                "commodity": "Pork",
                "year": 2023,
                "month": "August",
                "price_php_per_kg": 150.0,
                "source": "openstat_psa",
                "text": "Pork price",
            },
        ]
        store.seed_prices(rows)
        snapshot = build_price_snapshot_from_rows(rows)
        result = _list_openstat_commodities_impl(
            ToolExecutionContext(store, price_metadata=snapshot),
            commodity_type=None,
        )
        self.assertEqual(result.name, "list_openstat_commodities")
        self.assertEqual(result.result_count, 3)
        self.assertIn("Cereals", result.payload["commodity_types"])
        self.assertIn("Palay", result.payload["commodities_by_type"]["Cereals"])
        self.assertIn("Livestock", result.payload["commodity_types"])

    def test_price_without_location_skips_retrieval(self) -> None:
        farmer = infer_farmer_intent(
            message="Magkano palay ngayon?",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=None,
        )
        query_plan = build_query_plan(
            message="Magkano palay ngayon?",
            farmer_context=farmer,
            source_ids=None,
        )
        search_plan = build_search_plan(
            message="Magkano palay ngayon?",
            farmer_context=farmer,
            query_plan=query_plan,
            plan_rewrite=False,
        )
        self.assertTrue(search_plan.skip_retrieval)
        self.assertEqual(search_plan.tool_name, "none")

    def test_merge_corpus_results_rrf_dedupes_documents(self) -> None:
        shared = {
            "source_id": "irri",
            "doc_id": "same-doc",
            "title": "Same IRRI news",
            "url": "https://example.test/same",
            "text": "shared article",
            "score": 0.9,
        }
        other = {
            "source_id": "irri",
            "doc_id": "other-doc",
            "title": "Other IRRI news",
            "url": "https://example.test/other",
            "text": "other article",
            "score": 0.5,
        }
        source_shared = AgentSource(
            source_id="irri",
            title="Same IRRI news",
            url="https://example.test/same",
        )
        source_other = AgentSource(
            source_id="irri",
            title="Other IRRI news",
            url="https://example.test/other",
        )
        first = ToolExecutionResult(
            name="search_corpus",
            arguments={"query": "q1", "limit": 5},
            summary="1",
            result_count=2,
            payload={"hits": [dict(shared), dict(other)]},
            sources=[source_shared, source_other],
        )
        second = ToolExecutionResult(
            name="search_corpus",
            arguments={"query": "q2", "limit": 5},
            summary="1",
            result_count=1,
            payload={"hits": [dict(shared)]},
            sources=[source_shared],
        )
        merged = merge_corpus_results_rrf([first, second], limit=5)
        urls = [hit.get("url") for hit in merged.payload["hits"]]
        self.assertEqual(len(urls), 2)
        self.assertEqual(urls[0], "https://example.test/same")
        self.assertEqual(merged.result_count, 2)
        self.assertEqual(merged.arguments.get("queries"), ["q1", "q2"])

    def test_orchestrator_forces_price_tool_even_if_model_requests_corpus(self) -> None:
        store = FakeQdrantStore()
        store.seed_prices(
            [
                {
                    "geolocation": "Nueva Ecija",
                    "commodity_type": "Corn",
                    "commodity": "Corn [White]",
                    "year": 2026,
                    "month": "January",
                    "price_php_per_kg": 18.0,
                }
            ]
        )
        model = ToolCallingModel(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_bad",
                            "name": "search_corpus",
                            "args": {"query": "mais datos", "limit": 5},
                        }
                    ],
                ),
                FakeMessage(
                    '{"answer": "Average corn price is available for Nueva Ecija.", "tasklist": []}'
                ),
            ]
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="sa mais meron ba average price sa Nueva Ecija?",
                    mode=AgentMode.CHAT,
                ),
                _settings(),
                store=store,
            )

        self.assertEqual(response.tool_calls[0].name, "summarize_prices")
        self.assertTrue(
            any(call.name == "summarize_prices" for call in response.tool_calls)
        )
        self.assertTrue(any(warning.code == "tool_scope_blocked" for warning in response.warnings))

    def test_plan_no_longer_calls_llm_rewrite_upfront(self) -> None:
        farmer = infer_farmer_intent(
            message="May balita ba sa IRRI tungkol sa climate?",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=["irri"],
        )
        query_plan = build_query_plan(
            message="May balita ba sa IRRI tungkol sa climate?",
            farmer_context=farmer,
            source_ids=["irri"],
        )
        broken = MagicMock()
        broken.invoke.side_effect = RuntimeError("provider down")
        search_plan = build_search_plan(
            message="May balita ba sa IRRI tungkol sa climate?",
            farmer_context=farmer,
            query_plan=query_plan,
            plan_rewrite=True,
            plan_max_queries=3,
            model=broken,
        )
        self.assertEqual(search_plan.tool_name, "search_corpus")
        self.assertEqual(len(search_plan.search_queries), 1)
        self.assertIn("climate", search_plan.search_queries[0].lower())
        self.assertTrue(search_plan.allow_cascade_escalate)
        broken.invoke.assert_not_called()

    def test_news_exact_title_answer_still_used(self) -> None:
        store = FakeQdrantStore()
        store.seed_corpus(
            [
                {
                    "source_id": "irri",
                    "doc_id": "ghg",
                    "title": "IRRI joins global effort to modernize GHG measurement",
                    "url": "https://example.test/ghg",
                    "filename": "irri_news_2026-06-01.txt",
                    "text": "IRRI news about greenhouse gas measurement for rice.",
                }
            ]
        )
        model = ToolCallingModel(
            [
                FakeMessage(
                    '{"answer": "May bagong EMF3 gene breakthrough sa IRRI.", "tasklist": []}'
                ),
            ]
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="Ano ang latest news sa irri?",
                    mode=AgentMode.CHAT,
                    source_ids=["irri"],
                ),
                _settings(),
                store=store,
            )

        self.assertIn(
            "IRRI joins global effort to modernize GHG measurement",
            response.answer,
        )
        self.assertIn("https://example.test/ghg", response.answer)
        self.assertNotIn("EMF3", response.answer)


if __name__ == "__main__":
    unittest.main()
