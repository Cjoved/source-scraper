"""Tests for farmer intent + corpus source narrowing."""

from __future__ import annotations

import unittest

from src.agent.intent import infer_farmer_intent


class AgentIntentSourceScopeTests(unittest.TestCase):
    def test_philrice_news_query_scopes_to_philrice_news_only(self) -> None:
        result = infer_farmer_intent(
            message="ano yung latest news natin galing sa philrice?",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=None,
        )
        self.assertEqual(result.intent, "news_query")
        self.assertEqual(result.recommended_source_ids, ["philrice_news"])

    def test_irri_news_query_scopes_to_irri_only(self) -> None:
        result = infer_farmer_intent(
            message="ano yung latest news natin sa irri?",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=None,
        )
        self.assertEqual(result.intent, "news_query")
        self.assertEqual(result.recommended_source_ids, ["irri"])

    def test_generic_news_keeps_both_news_sources(self) -> None:
        result = infer_farmer_intent(
            message="ano yung latest news tungkol sa palay?",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=None,
        )
        self.assertEqual(result.intent, "news_query")
        self.assertEqual(result.recommended_source_ids, ["philrice_news", "irri"])

    def test_explicit_source_ids_win(self) -> None:
        result = infer_farmer_intent(
            message="latest news from philrice",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=["irri"],
        )
        self.assertEqual(result.recommended_source_ids, ["irri"])


if __name__ == "__main__":
    unittest.main()
