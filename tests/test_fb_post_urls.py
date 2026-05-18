import unittest

from src.scraper.parsers.fb_post_urls import clean_permalink, is_comment_href


class TestFbPostUrls(unittest.TestCase):
    def test_comment_path_rejected(self) -> None:
        href = "https://www.facebook.com/comment/12345"
        self.assertIsNone(clean_permalink(href, "https://www.facebook.com"))

    def test_strips_comment_id_from_post_url(self) -> None:
        href = "https://www.facebook.com/user/posts/pfbidABC?comment_id=123"
        self.assertTrue(is_comment_href(href))
        clean = clean_permalink(href, "https://www.facebook.com")
        self.assertEqual(clean, "https://www.facebook.com/user/posts/pfbidABC")

    def test_clean_post_link(self) -> None:
        href = (
            "https://www.facebook.com/liezl.p.aquino/posts/pfbid0ABC"
            "?__cft__=xyz&comment_id=999"
        )
        clean = clean_permalink(href, "https://www.facebook.com")
        self.assertIsNotNone(clean)
        assert clean is not None
        self.assertNotIn("comment_id", clean)
        self.assertNotIn("?", clean)
        self.assertIn("/posts/pfbid0ABC", clean)
