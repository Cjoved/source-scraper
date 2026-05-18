import unittest
from pathlib import Path

from src.scraper.parsers.fb_post_urls import extract_post_id_from_href
from src.scraper.parsers.fb_profile_posts import parse_top_post_from_html

FIXTURE = Path(__file__).parent / "fixtures" / "fb_profile_timeline.html"
FIXTURE_MOTION = Path(__file__).parent / "fixtures" / "fb_profile_timeline_motion.html"
FIXTURE_PINNED_SKIP = Path(__file__).parent / "fixtures" / "fb_profile_pinned_then_post.html"
FIXTURE_OTHER_POSTS = Path(__file__).parent / "fixtures" / "fb_profile_other_posts_section.html"
PROFILE = "https://www.facebook.com/liezl.p.aquino"


class TestFbPostId(unittest.TestCase):
    def test_pfbid_from_posts_path(self) -> None:
        href = "https://www.facebook.com/user/posts/pfbid02ABC123xyz"
        self.assertEqual(extract_post_id_from_href(href), "02ABC123xyz")


class TestParseTopPost(unittest.TestCase):
    def test_fixture_post(self) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        post = parse_top_post_from_html(html, PROFILE)
        self.assertIsNotNone(post)
        assert post is not None
        self.assertEqual(post.post_id, "02ABC123xyz")
        self.assertIn("/posts/pfbid02ABC123xyz", post.permalink)
        self.assertIn("Palay wet", post.text)
        self.assertEqual(post.posted_at, "2026-05-18T15:00:00+08:00")
        self.assertEqual(post.posted_at_iso, "2026-05-18T15:00:00+08:00")
        self.assertEqual(len(post.image_urls), 2)
        self.assertTrue(all("scontent" in u for u in post.image_urls))
        self.assertTrue(any("example_large" in u for u in post.image_urls))

    def test_motion_article_fixture(self) -> None:
        html = FIXTURE_MOTION.read_text(encoding="utf-8")
        post = parse_top_post_from_html(html, PROFILE)
        self.assertIsNotNone(post)
        assert post is not None
        self.assertEqual(post.post_id, "0MotionPost99")
        self.assertIn("Part3 Towns", post.text)
        self.assertEqual(post.posted_at, "May 12 at 3:00 PM")

    def test_skips_pinned_takes_next_post(self) -> None:
        html = FIXTURE_PINNED_SKIP.read_text(encoding="utf-8")
        post = parse_top_post_from_html(html, PROFILE)
        self.assertIsNotNone(post)
        assert post is not None
        self.assertEqual(post.post_id, "LATEST456")
        self.assertIn("Palay wet", post.text)
        self.assertEqual(post.posted_at_iso, "2026-05-10T09:30:00+08:00")
        self.assertNotIn("PINNED", post.text)

    def test_other_posts_section_not_comment(self) -> None:
        html = FIXTURE_OTHER_POSTS.read_text(encoding="utf-8")
        post = parse_top_post_from_html(html, PROFILE)
        self.assertIsNotNone(post)
        assert post is not None
        self.assertEqual(post.post_id, "OTHERPOST01")
        self.assertIn("P10,125", post.text)
        self.assertIn("Tulong Pinansyal", post.text)
        self.assertNotIn("Derlina", post.text)
        self.assertNotIn("comment_id", post.permalink.lower())
        self.assertEqual(post.posted_at_iso, "2026-05-18T14:00:00+08:00")
        self.assertTrue(any("other_posts_target" in u for u in post.image_urls))
