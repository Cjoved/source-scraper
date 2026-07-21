"""Tests for LLM structured Plan-and-Execute planner."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.agent.orchestrator import run_agent_chat
from src.agent.plan_agent import llm_build_agent_plan, validate_agent_plan
from src.agent.plan_schema import AgentPlan, PlanStep
from src.api.schemas import AgentChatRequest, AgentMode
from tests.fakes.fake_store import FakeQdrantStore
from tests.test_agent_orchestrator import FakeMessage, ToolCallingModel, _settings


class _StructuredPlanModel:
    """Model that returns a fixed AgentPlan via with_structured_output."""

    def __init__(self, plan: AgentPlan, *, synthesize: object | None = None) -> None:
        self.plan = plan
        self.synthesize = synthesize or FakeMessage(
            '{"answer": "Ok based on tools.", "tasklist": []}'
        )
        self.invocations: list[object] = []
        self.bound_tools: list[object] = []
        self._mode = "chat"

    def with_structured_output(self, schema: object) -> "_StructuredPlanModel":
        del schema
        clone = _StructuredPlanModel(self.plan, synthesize=self.synthesize)
        clone._mode = "plan"
        clone.bound_tools = self.bound_tools
        return clone

    def bind_tools(self, tools: list[object]) -> "_StructuredPlanModel":
        self.bound_tools = tools
        return self

    def invoke(self, input: object, config: object | None = None, **kwargs: object) -> object:
        del config, kwargs
        self.invocations.append(input)
        if self._mode == "plan":
            return self.plan
        return self.synthesize


class _FailingPlannerModel(ToolCallingModel):
    """Chat model whose planner path always fails; synthesis uses ToolCallingModel."""

    def with_structured_output(self, schema: object) -> "_FailingPlannerModel":
        del schema
        raise RuntimeError("structured output unsupported")

    def invoke(self, input: object, config: object | None = None, **kwargs: object) -> object:
        # First invoke may be planner JSON attempt from llm_build_agent_plan
        if not self.invocations:
            self.invocations.append(input)
            raise RuntimeError("planner timeout")
        return super().invoke(input, config, **kwargs)


class TestLlmPlanAgent(unittest.TestCase):
    def test_validate_multi_step_plan(self) -> None:
        plan = AgentPlan(
            language="tl",
            goal="presyo at balita",
            primary_intent="mixed",
            steps=[
                PlanStep(
                    tool="summarize_prices",
                    args={"geolocation": "Isabela", "commodity": "Rice"},
                    rationale="presyo",
                ),
                PlanStep(
                    tool="search_corpus",
                    args={"query": "Isabela rice news", "source_ids": ["irri"]},
                    rationale="balita",
                ),
            ],
        )
        validated = validate_agent_plan(
            plan,
            message="Magkano bigas sa Isabela at ano latest news?",
            location=None,
            crop=None,
            max_steps=3,
        )
        self.assertFalse(validated.skip_retrieval)
        self.assertEqual(len(validated.search_plans), 2)
        self.assertEqual(validated.search_plans[0].tool_name, "summarize_prices")
        self.assertEqual(validated.search_plans[1].tool_name, "search_corpus")
        self.assertEqual(validated.primary_intent, "mixed")
        self.assertEqual(
            validated.planned_tool_names,
            frozenset({"summarize_prices", "search_corpus"}),
        )

    def test_validate_clarification_without_location(self) -> None:
        plan = AgentPlan(
            language="tl",
            goal="presyo",
            primary_intent="price_query",
            needs_clarification=False,
            steps=[
                PlanStep(tool="summarize_prices", args={"commodity": "Palay"}, rationale="price"),
            ],
        )
        validated = validate_agent_plan(
            plan,
            message="Magkano ang palay?",
            location=None,
            crop="palay",
        )
        self.assertTrue(validated.needs_clarification)
        self.assertTrue(validated.skip_retrieval)
        self.assertEqual(validated.search_plans, [])
        self.assertIsNotNone(validated.clarification_question)

    def test_validate_clamps_source_ids_and_steps(self) -> None:
        plan = AgentPlan(
            language="en",
            goal="news",
            primary_intent="news_query",
            steps=[
                PlanStep(
                    tool="search_corpus",
                    args={"source_ids": ["irri", "evil_source", "philrice_news"]},
                ),
                PlanStep(tool="summarize_prices", args={"geolocation": "Tarlac"}),
                PlanStep(tool="summarize_yield", args={"province": "Tarlac"}),
                PlanStep(tool="search_prices", args={"query": "extra"}),
            ],
        )
        validated = validate_agent_plan(
            plan,
            message="latest irri news and tarlac prices and yield",
            location="Tarlac",
            max_steps=2,
        )
        self.assertEqual(len(validated.search_plans), 2)
        self.assertTrue(any(w.code == "plan_steps_clamped" for w in validated.warnings))
        corpus = validated.search_plans[0]
        self.assertEqual(corpus.tool_args.get("source_ids"), ["irri", "philrice_news"])

    def test_orchestrator_executes_multi_step_llm_plan(self) -> None:
        store = FakeQdrantStore()
        store.seed_prices(
            [
                {
                    "geolocation": "Isabela",
                    "commodity_type": "Cereals",
                    "commodity": "RICE, WELL-MILLED, 1 KG",
                    "year": 2025,
                    "month": "January",
                    "price_php_per_kg": 42.0,
                }
            ]
        )
        store.seed_corpus(
            [
                {
                    "source_id": "irri",
                    "doc_id": "n1",
                    "title": "Isabela rice advisory from IRRI",
                    "url": "https://example.test/isabela-news",
                    "text": "News about Isabela rice.",
                }
            ]
        )
        plan = AgentPlan(
            language="tl",
            goal="presyo at balita",
            primary_intent="mixed",
            steps=[
                PlanStep(
                    tool="summarize_prices",
                    args={"geolocation": "Isabela", "commodity": "Bigas", "year_min": 2025, "year_max": 2025},
                ),
                PlanStep(
                    tool="search_corpus",
                    args={"query": "Isabela rice", "source_ids": ["irri"], "sort_by": "latest"},
                ),
            ],
        )
        model = _StructuredPlanModel(plan)
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="Magkano bigas sa Isabela at ano latest news?",
                    mode=AgentMode.CHAT,
                ),
                _settings(agent_llm_planner=True, agent_max_tool_calls=4),
                store=store,
            )

        names = [call.name for call in response.tool_calls]
        self.assertIn("summarize_prices", names)
        self.assertIn("search_corpus", names)
        self.assertFalse(any(w.code == "plan_llm_fallback" for w in response.warnings))

    def test_novel_phrasing_uses_llm_plan_not_keywords(self) -> None:
        """Without magkano/presyo keywords, LLM plan still routes to summarize_prices."""
        store = FakeQdrantStore()
        store.seed_prices(
            [
                {
                    "geolocation": "Isabela",
                    "commodity_type": "Cereals",
                    "commodity": "RICE, WELL-MILLED, 1 KG",
                    "year": 2025,
                    "month": "June",
                    "price_php_per_kg": 40.0,
                }
            ]
        )
        plan = AgentPlan(
            language="tl",
            goal="bigas price last year",
            primary_intent="price_query",
            steps=[
                PlanStep(
                    tool="summarize_prices",
                    args={
                        "geolocation": "Isabela",
                        "commodity": "Bigas",
                        "year_min": 2025,
                        "year_max": 2025,
                    },
                ),
            ],
        )
        model = _StructuredPlanModel(
            plan,
            synthesize=FakeMessage(
                '{"answer": "Average price available for Isabela.", "tasklist": []}'
            ),
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="ilan ang bayad sa bigas sa Isabela last year",
                    mode=AgentMode.CHAT,
                ),
                _settings(agent_llm_planner=True),
                store=store,
            )

        self.assertEqual(response.tool_calls[0].name, "summarize_prices")
        self.assertEqual(response.tool_calls[0].arguments.get("geolocation"), "Isabela")

    def test_planner_failure_falls_back_to_keyword_plan(self) -> None:
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
        model = _FailingPlannerModel(
            [
                FakeMessage(
                    '{"answer": "Average corn price is available for Nueva Ecija.", "tasklist": []}'
                ),
            ]
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="Magkano ang average farmgate price ng mais sa Nueva Ecija?",
                    mode=AgentMode.CHAT,
                ),
                _settings(agent_llm_planner=True),
                store=store,
            )

        self.assertTrue(any(w.code == "plan_llm_fallback" for w in response.warnings))
        self.assertTrue(any(call.name == "summarize_prices" for call in response.tool_calls))

    def test_news_exact_titles_with_llm_plan(self) -> None:
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
        plan = AgentPlan(
            language="tl",
            goal="latest irri news",
            primary_intent="news_query",
            steps=[
                PlanStep(
                    tool="search_corpus",
                    args={"query": "IRRI latest news", "source_ids": ["irri"], "sort_by": "latest"},
                ),
            ],
        )
        model = _StructuredPlanModel(
            plan,
            synthesize=FakeMessage(
                '{"answer": "May bagong EMF3 gene breakthrough sa IRRI.", "tasklist": []}'
            ),
        )
        with patch("src.agent.orchestrator.create_chat_model", return_value=model):
            response = run_agent_chat(
                AgentChatRequest(
                    message="Ano ang latest news sa irri?",
                    mode=AgentMode.CHAT,
                    source_ids=["irri"],
                ),
                _settings(agent_llm_planner=True),
                store=store,
            )

        self.assertIn(
            "IRRI joins global effort to modernize GHG measurement",
            response.answer,
        )
        self.assertIn("https://example.test/ghg", response.answer)
        self.assertNotIn("EMF3", response.answer)

    def test_llm_build_agent_plan_fail_open(self) -> None:
        broken = ToolCallingModel([])
        broken.invoke = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))  # type: ignore[method-assign]
        result = llm_build_agent_plan(broken, message="hello")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
