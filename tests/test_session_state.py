from __future__ import annotations

import unittest

from src.agent.session_state import (
    resolve_session_state,
    session_state_context_text,
    update_session_state,
)
from src.agent.query_planner import AgentQueryPlan, build_query_plan
from src.agent.intent import infer_farmer_intent
from src.api.schemas import (
    AgentChatMessage,
    AgentChatRequest,
    AgentSessionState,
    AgentSource,
    AgentToolCall,
)


class SessionStateTests(unittest.TestCase):
    def test_resolve_carries_prior_location_and_crop(self) -> None:
        body = AgentChatRequest(
            message="Magkano ulit?",
            session_state=AgentSessionState(
                location="Nueva Ecija",
                crop="palay",
                last_intent="price_query",
                last_tool_name="summarize_prices",
                last_tool_args={"geolocation": "Nueva Ecija", "commodity": "Palay"},
            ),
        )

        resolved = resolve_session_state(body)

        self.assertEqual(resolved.location, "Nueva Ecija")
        self.assertEqual(resolved.crop, "palay")
        self.assertEqual(resolved.last_tool_name, "summarize_prices")

    def test_resolve_extracts_location_from_user_history(self) -> None:
        body = AgentChatRequest(
            message="Magkano ulit?",
            history=[
                AgentChatMessage(role="user", content="Magkano palay sa Nueva Ecija?"),
                AgentChatMessage(role="assistant", content="Average price is PHP 25/kg."),
            ],
        )

        resolved = resolve_session_state(body)

        self.assertEqual(resolved.location, "Nueva Ecija")

    def test_update_only_from_tool_calls(self) -> None:
        state = AgentSessionState(location="Nueva Ecija", crop="palay")
        query_plan = AgentQueryPlan(intent="price_query", tool_preference="summarize_prices")
        tool_calls = [
            AgentToolCall(
                name="summarize_prices",
                arguments={"geolocation": "Nueva Ecija", "commodity": "Palay"},
                summary="Computed price summary.",
                result_count=3,
            )
        ]

        updated = update_session_state(
            state,
            query_plan=query_plan,
            tool_calls=tool_calls,
            sources=[],
        )

        self.assertEqual(updated.last_intent, "price_query")
        self.assertEqual(updated.last_tool_name, "summarize_prices")
        self.assertEqual(updated.last_tool_args, {"geolocation": "Nueva Ecija", "commodity": "Palay"})
        self.assertEqual(updated.location, "Nueva Ecija")

    def test_build_query_plan_uses_session_location(self) -> None:
        farmer_context = infer_farmer_intent(
            message="Magkano ulit?",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=None,
            session=AgentSessionState(location="Nueva Ecija", last_intent="price_query"),
        )
        plan = build_query_plan(
            message="Magkano ulit?",
            farmer_context=farmer_context,
            source_ids=None,
            session=AgentSessionState(location="Nueva Ecija"),
        )

        self.assertEqual(plan.location, "Nueva Ecija")

    def test_session_state_context_text(self) -> None:
        text = session_state_context_text(
            AgentSessionState(
                location="Nueva Ecija",
                crop="palay",
                last_intent="price_query",
                last_tool_name="summarize_prices",
            )
        )

        self.assertIn("location=Nueva Ecija", text)
        self.assertIn("last_tool=summarize_prices", text)


if __name__ == "__main__":
    unittest.main()
