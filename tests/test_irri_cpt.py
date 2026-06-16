import tempfile
import unittest
from pathlib import Path

from src.openstat.services.irri import _safe_doc_id, txt_to_cpt_records


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

    def test_txt_to_cpt_records_uses_url_slug_for_duplicate_titles(self) -> None:
        title = "Golden Rice meets food safety standards in three global leading regulatory agencies _ International Rice Research Institute"
        body = "This is enough IRRI body content to pass min chunk chars. " * 5
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "a.txt"
            p2 = Path(tmp) / "b.txt"
            p1.write_text(
                "URL: https://www.irri.org/news-and-events/news/golden-rice-meets-food-safety-standards-three-global-leading-regulatory\n"
                f"Title: {title}\n\n{body}",
                encoding="utf-8",
            )
            p2.write_text(
                "URL: https://www.irri.org/news-and-events/news/golden-rice-meets-food-safety-standards-three-global-leading-regulatory-0\n"
                f"Title: {title}\n\n{body}",
                encoding="utf-8",
            )

            r1 = txt_to_cpt_records(str(p1))
            r2 = txt_to_cpt_records(str(p2))
            self.assertEqual(len(r1), 1)
            self.assertEqual(len(r2), 1)
            self.assertNotEqual(r1[0]["doc_id"], r2[0]["doc_id"])
            self.assertIn(
                "golden_rice_meets_food_safety_standards_in_three_global_leading_regulatory_agencies",
                r1[0]["doc_id"],
            )
            self.assertIn(
                "golden_rice_meets_food_safety_standards_in_three_global_leading_regulatory_agencies",
                r2[0]["doc_id"],
            )


if __name__ == "__main__":
    unittest.main()
