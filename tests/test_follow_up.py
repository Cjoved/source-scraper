from __future__ import annotations

import unittest

from src.agent.follow_up import (
    looks_like_corpus_continuation,
    looks_like_data_continuation,
    looks_like_fresh_corpus_query,
    parse_source_indexes,
    prior_assistant_sources,
    resolve_corpus_follow_up,
    resolve_data_follow_up,
    resolve_referenced_sources,
)
from src.api.schemas import AgentChatMessage, AgentChatRequest, AgentSessionState, AgentSource


class FollowUpTests(unittest.TestCase):
    def test_prior_assistant_sources_returns_latest_assistant_sources(self) -> None:
        sources = [
            AgentSource(source_id="irri", title="Latest IRRI news", url="https://example.test/1"),
        ]
        history = [
            AgentChatMessage(role="user", content="latest news?"),
            AgentChatMessage(role="assistant", content="Here are items.", sources=sources),
        ]

        self.assertEqual(prior_assistant_sources(history), sources)

    def test_looks_like_data_continuation_uses_session_not_ulit_keyword(self) -> None:
        session = AgentSessionState(
            last_intent="price_query",
            last_tool_name="summarize_prices",
            last_tool_args={"geolocation": "Nueva Ecija", "commodity": "Palay"},
        )

        self.assertTrue(looks_like_data_continuation("same province ba?", session))
        self.assertTrue(looks_like_data_continuation("Magkano ulit?", session))

    def test_resolve_corpus_follow_up_ignores_price_sources(self) -> None:
        sources = [
            AgentSource(source_id="openstat_price_records", title="Price row", snippet="PHP 25/kg"),
        ]
        body = AgentChatRequest(
            message="magkano ulit?",
            history=[
                AgentChatMessage(role="assistant", content="Price answer.", sources=sources),
            ],
        )

        self.assertIsNone(resolve_corpus_follow_up(body))

    def test_resolve_data_follow_up_reuses_last_price_tool(self) -> None:
        session = AgentSessionState(
            last_intent="price_query",
            last_tool_name="summarize_prices",
            last_tool_args={"geolocation": "Nueva Ecija", "commodity": "Palay"},
            location="Nueva Ecija",
        )
        body = AgentChatRequest(message="Magkano ulit?")

        follow_up = resolve_data_follow_up(body, session, current_intent="price_query")

        self.assertIsNotNone(follow_up)
        assert follow_up is not None
        self.assertEqual(follow_up.tool_name, "summarize_prices")
        self.assertEqual(follow_up.tool_args["geolocation"], "Nueva Ecija")

    def test_resolve_corpus_follow_up_requires_prior_sources(self) -> None:
        body = AgentChatRequest(
            message="ano ang mga date nitong limang news na ito?",
            history=[AgentChatMessage(role="assistant", content="Narito ang listahan.")],
        )

        self.assertIsNone(resolve_corpus_follow_up(body))

    def test_resolve_corpus_follow_up_returns_prior_sources(self) -> None:
        sources = [
            AgentSource(source_id="irri", title="IRRI item", url="https://example.test/irri"),
        ]
        body = AgentChatRequest(
            message="ano ang mga date nitong limang news na ito?",
            history=[
                AgentChatMessage(role="user", content="latest news?"),
                AgentChatMessage(role="assistant", content="Narito ang listahan.", sources=sources),
            ],
        )

        follow_up = resolve_corpus_follow_up(body)

        self.assertIsNotNone(follow_up)
        assert follow_up is not None
        self.assertEqual(list(follow_up.sources), sources)

    def test_parse_source_indexes_reads_hash_and_ordinals(self) -> None:
        self.assertEqual(parse_source_indexes("yung #2 kailan?"), [2])
        self.assertEqual(parse_source_indexes("petsa ng pangalawa"), [2])
        self.assertEqual(parse_source_indexes("article no. 2 pa explain"), [2])

    def test_parse_source_indexes_ignores_trailing_ito_when_no_is_present(self) -> None:
        sources = [
            AgentSource(source_id="irri", title="First", url="https://example.test/1"),
            AgentSource(source_id="irri", title="Second", url="https://example.test/2"),
        ]

        resolved = resolve_referenced_sources(
            "article no. 2 kailan na upload ito?",
            sources,
        )

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].title, "Second")

    def test_resolve_corpus_follow_up_accepts_explain_only_message(self) -> None:
        sources = [
            AgentSource(
                source_id="irri",
                title="India seeks faster delivery",
                url="https://example.test/2",
                snippet="India must accelerate climate-resilient rice.",
            ),
        ]
        body = AgentChatRequest(
            message="pa explain naman",
            session_state=AgentSessionState(last_intent="news_query", last_tool_name="search_corpus"),
            history=[
                AgentChatMessage(role="user", content="latest news?"),
                AgentChatMessage(role="assistant", content="Narito ang listahan.", sources=sources),
            ],
        )

        follow_up = resolve_corpus_follow_up(body)

        self.assertIsNotNone(follow_up)
        assert follow_up is not None
        self.assertEqual(len(follow_up.sources), 1)

    def test_resolve_referenced_sources_keeps_list_when_reference_is_ambiguous(self) -> None:
        sources = [
            AgentSource(source_id="irri", title="First", url="https://example.test/1"),
            AgentSource(source_id="irri", title="Second", url="https://example.test/2"),
        ]

        resolved = resolve_referenced_sources("kailan yung article?", sources)

        self.assertEqual(len(resolved), 2)

    def test_looks_like_corpus_continuation_uses_session_not_keywords(self) -> None:
        sources = [
            AgentSource(source_id="irri", title="IRRI item", url="https://example.test/irri"),
        ]
        session = AgentSessionState(last_intent="news_query", last_tool_name="search_corpus")

        self.assertTrue(
            looks_like_corpus_continuation(
                "pa explain naman",
                session=session,
                prior=sources,
            )
        )
        self.assertFalse(looks_like_fresh_corpus_query("pa explain naman"))

    def test_looks_like_fresh_corpus_query_blocks_new_search(self) -> None:
        sources = [
            AgentSource(source_id="irri", title="IRRI item", url="https://example.test/irri"),
        ]
        session = AgentSessionState(last_intent="news_query")

        self.assertFalse(
            looks_like_corpus_continuation(
                "ano yung ating latest news na meron tayo?",
                session=session,
                prior=sources,
            )
        )

    def test_cross_domain_blocks_price_question_after_news(self) -> None:
        sources = [AgentSource(source_id="irri", title="News", url="https://example.test/1")]
        session = AgentSessionState(last_intent="news_query", last_tool_name="search_corpus")

        self.assertFalse(
            looks_like_corpus_continuation(
                "magkano presyo ng palay sa Nueva Ecija?",
                session=session,
                prior=sources,
            )
        )

    def test_resolve_referenced_sources_count_caps_list(self) -> None:
        sources = [
            AgentSource(source_id="irri", title=f"Item {idx}", url=f"https://example.test/{idx}")
            for idx in range(1, 6)
        ]

        resolved = resolve_referenced_sources("petsa nitong limang news na ito?", sources)

        self.assertEqual(len(resolved), 5)

    def test_resolve_corpus_follow_up_subsets_to_referenced_index(self) -> None:
        sources = [
            AgentSource(source_id="irri", title="First", url="https://example.test/1"),
            AgentSource(source_id="irri", title="Second", url="https://example.test/2"),
        ]
        body = AgentChatRequest(
            message="yung #2 kailan na-post?",
            history=[
                AgentChatMessage(role="user", content="latest news?"),
                AgentChatMessage(role="assistant", content="Narito ang listahan.", sources=sources),
            ],
        )

        follow_up = resolve_corpus_follow_up(body)

        self.assertIsNotNone(follow_up)
        assert follow_up is not None
        self.assertEqual(len(follow_up.sources), 1)
        self.assertEqual(follow_up.sources[0].title, "Second")


if __name__ == "__main__":
    unittest.main()
