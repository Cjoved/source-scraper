"""Tests for farmer intent + corpus source narrowing."""

from __future__ import annotations

import unittest

from src.agent.intent import infer_farmer_intent, infer_reply_language, is_taglish
from src.api.schemas import AgentSessionState


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

    def test_available_crops_question_is_metadata_query(self) -> None:
        result = infer_farmer_intent(
            message="Ano pa ang crops na available sa data?",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=None,
        )
        self.assertEqual(result.intent, "metadata_query")


    def test_carried_location_from_session_when_message_has_no_province(self) -> None:
        result = infer_farmer_intent(
            message="Magkano ulit?",
            user_type="farmer",
            location=None,
            crop=None,
            language=None,
            source_ids=None,
            session=AgentSessionState(
                location="Nueva Ecija",
                last_intent="price_query",
            ),
        )

        self.assertEqual(result.intent, "price_query")
        self.assertEqual(result.location, "Nueva Ecija")
        self.assertIsNone(result.clarification_question)

    def test_infer_reply_language_prefers_taglish_from_message(self) -> None:
        self.assertEqual(
            infer_reply_language("Kailan na-upload yung article?", explicit_language="en"),
            "taglish",
        )
        self.assertEqual(
            infer_reply_language("may news ba tayo regarding sa drone?", explicit_language="en"),
            "taglish",
        )

    def test_is_taglish_detects_tagalog_markers(self) -> None:
        self.assertTrue(is_taglish(None, "Ano ang petsa nito?"))
        self.assertFalse(is_taglish("en", "When was this published?"))


if __name__ == "__main__":
    unittest.main()
