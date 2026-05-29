import unittest

from src.openstat.services.irri import _safe_doc_id


class IrriDocIdTests(unittest.TestCase):
    def test_slug_from_title(self) -> None:
        self.assertEqual(
            _safe_doc_id("Rice Research Highlights 2024"),
            "rice_research_highlights_2024",
        )

    def test_strips_irri_suffix_pattern(self) -> None:
        from src.openstat.services.irri import _clean_title_for_id

        title = "Some Article | International Rice Research Institute"
        cleaned = _clean_title_for_id(title)
        doc_id = _safe_doc_id(cleaned)
        self.assertNotIn("international", doc_id)
        self.assertTrue(doc_id.startswith("some_article"))

    def test_unknown_fallback(self) -> None:
        self.assertEqual(_safe_doc_id(""), "irri_unknown")


if __name__ == "__main__":
    unittest.main()
