"""Tests for Stage-1 / Stage-2 corpus retrieval cascade."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.agent.intent import infer_farmer_intent
from src.agent.orchestrator import run_agent_chat
from src.agent.plan_agent import (
    build_search_plan,
    is_vague_listing_query,
    is_weak_corpus_result,
)
from src.agent.query_planner import build_query_plan
from src.agent.tools import ToolExecutionResult
from src.api.schemas import AgentChatRequest, AgentMode, AgentSource
from tests.fakes.fake_store import FakeQdrantStore
from tests.test_agent_orchestrator import FakeMessage, ToolCallingModel, _settings


class TestRetrievalCascade(unittest.TestCase):
    def test_plan_starts_with_single_deterministic_query(self) -> None:
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
        broken.invoke.side_effect = RuntimeError("should not be called during plan")
        search_plan = build_search_plan(
            message="May balita ba sa IRRI tungkol sa climate?",
            farmer_context=farmer,
            query_plan=query_plan,
            plan_rewrite=True,
            plan_max_queries=3,
            model=broken,
        )
        self.assertEqual(len(search_plan.search_queries), 1)
        self.assertTrue(search_plan.allow_cascade_escalate)
        broken.invoke.assert_not_called()

    def test_strong_stage1_does_not_call_llm_rewrite(self) -> None:
        store = FakeQdrantStore()
        store.seed_corpus(
            [
                {
                    "source_id": "irri",
                    "doc_id": "climate-1",
                    "title": "IRRI climate resilient rice",
                    "url": "https://example.test/climate",
                    "text": "IRRI climate adaptation research for rice farmers.",
                    "score": 0.9,
                }
            ]
        )
        rewrite_spy = MagicMock(return_value=["climate rice IRRI"])
        model = ToolCallingModel(
            [FakeMessage('{"answer": "May climate news mula sa IRRI.", "tasklist": []}')]
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            with patch(
                "src.agent.orchestrator.rewrite_corpus_queries_with_llm",
                rewrite_spy,
            ):
                response = run_agent_chat(
                    AgentChatRequest(
                        message="IRRI climate resilient rice research",
                        mode=AgentMode.CHAT,
                        source_ids=["irri"],
                    ),
                    _settings(agent_plan_rewrite=True, agent_cascade_min_score=0.01),
                    store=store,
                )

        rewrite_spy.assert_not_called()
        self.assertFalse(any(w.code == "cascade_escalated" for w in response.warnings))
        self.assertGreaterEqual(response.tool_calls[0].result_count, 1)

    def test_zero_hits_escalates_when_rewrite_enabled(self) -> None:
        store = FakeQdrantStore()
        rewrite_spy = MagicMock(return_value=["alternate rice query"])
        model = ToolCallingModel(
            [FakeMessage('{"answer": "Walang matching news.", "tasklist": []}')]
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            with patch(
                "src.agent.orchestrator.rewrite_corpus_queries_with_llm",
                rewrite_spy,
            ):
                response = run_agent_chat(
                    AgentChatRequest(
                        message="Find nonexistent zzqx news topic xyzzy",
                        mode=AgentMode.CHAT,
                        source_ids=["irri"],
                    ),
                    _settings(agent_plan_rewrite=True, agent_plan_max_queries=3),
                    store=store,
                )

        rewrite_spy.assert_called_once()
        self.assertTrue(
            any(w.code in {"cascade_escalated", "cascade_skipped"} for w in response.warnings)
        )

    def test_weak_helper_rules(self) -> None:
        empty = ToolExecutionResult(
            name="search_corpus",
            arguments={"query": "q", "limit": 5},
            summary="0",
            result_count=0,
            payload={"hits": []},
            sources=[],
        )
        self.assertTrue(
            is_weak_corpus_result(
                empty,
                min_score=0.15,
                limit=5,
                message="latest news",
                search_query="latest agriculture rice news",
                sort_by="relevance",
            )
        )
        strong = ToolExecutionResult(
            name="search_corpus",
            arguments={"query": "q", "limit": 5},
            summary="1",
            result_count=1,
            payload={"hits": [{"score": 0.8, "title": "x"}]},
            sources=[AgentSource(title="x")],
        )
        self.assertFalse(
            is_weak_corpus_result(
                strong,
                min_score=0.15,
                limit=5,
                message="IRRI climate rice",
                search_query="IRRI climate rice news",
                sort_by="relevance",
            )
        )
        self.assertTrue(is_vague_listing_query("Ano ang latest agri news?", "latest rice agriculture news"))
        self.assertFalse(is_vague_listing_query("IRRI climate AWD", "IRRI climate rice news"))

    def test_latest_sort_skips_rerank_path(self) -> None:
        store = FakeQdrantStore()
        store.seed_corpus(
            [
                {
                    "source_id": "irri",
                    "doc_id": "n1",
                    "title": "Exact Latest IRRI Title",
                    "url": "https://example.test/n1",
                    "filename": "irri_news_2026-06-01.txt",
                    "text": "IRRI news body",
                }
            ]
        )
        model = ToolCallingModel(
            [FakeMessage('{"answer": "invented EMF3 headline", "tasklist": []}')]
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            with patch("src.agent.tools.rerank_hit_payloads") as rerank_spy:
                response = run_agent_chat(
                    AgentChatRequest(
                        message="Ano ang latest news sa irri?",
                        mode=AgentMode.CHAT,
                        source_ids=["irri"],
                    ),
                    _settings(agent_plan_rewrite=False, agent_rerank_enabled=True),
                    store=store,
                )
        rerank_spy.assert_not_called()
        self.assertIn("Exact Latest IRRI Title", response.answer)
        self.assertNotIn("EMF3", response.answer)


if __name__ == "__main__":
    unittest.main()
