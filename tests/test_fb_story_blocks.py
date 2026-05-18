import unittest
from pathlib import Path

from src.scraper.parsers.fb_profile_posts import parse_daily_posts_from_page, parse_top_post_from_html
from src.scraper.parsers.fb_story_blocks import (
    parse_stories_after_other_posts,
    parse_story_after_other_posts,
    resolve_post_permalink,
)

FIXTURE = Path(__file__).parent / "fixtures" / "fb_profile_story_block.html"
FIXTURE_DAILY = Path(__file__).parent / "fixtures" / "fb_profile_daily_two_posts.html"
DEBUG = Path(__file__).parent.parent / "data" / "prism_processed" / "fb_debug_last.html"
PROFILE = "https://www.facebook.com/liezl.p.aquino"


class TestResolvePermalink(unittest.TestCase):
    def test_strips_comment_id_from_post_url(self) -> None:
        href = (
            "https://www.facebook.com/liezl.p.aquino/posts/pfbidABC123"
            "?comment_id=4366756573605855"
        )
        clean = resolve_post_permalink(href, PROFILE)
        self.assertIsNotNone(clean)
        assert clean is not None
        self.assertNotIn("comment_id", clean)
        self.assertIn("/posts/pfbidABC123", clean)


class TestStoryBlockFixture(unittest.TestCase):
    def test_story_after_other_posts(self) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        post = parse_story_after_other_posts(
            __import__("parsel").Selector(text=html), PROFILE
        )
        self.assertIsNotNone(post)
        assert post is not None
        self.assertIn("P10,125", post.text)
        self.assertEqual(post.post_id, "STORYBLOCK01")
        self.assertNotIn("comment_id", post.permalink)

    def test_html_parser_uses_story_path(self) -> None:
        html = FIXTURE.read_text(encoding="utf-8")
        post = parse_top_post_from_html(html, PROFILE)
        self.assertIsNotNone(post)
        assert post is not None
        self.assertIn("Tulong Pinansyal", post.text)

    def test_daily_collects_today_only(self) -> None:
        from parsel import Selector

        html = FIXTURE_DAILY.read_text(encoding="utf-8")
        posts = parse_daily_posts_from_page(
            Selector(text=html),
            PROFILE,
            tz_name="Asia/Manila",
            max_posts=10,
            max_age_hours=23,
        )
        ids = {p.post_id for p in posts}
        self.assertEqual(ids, {"POSTA01", "POSTB02"})

    def test_list_multiple_stories(self) -> None:
        from parsel import Selector

        html = FIXTURE_DAILY.read_text(encoding="utf-8")
        posts = parse_stories_after_other_posts(Selector(text=html), PROFILE, max_posts=10)
        self.assertGreaterEqual(len(posts), 2)


@unittest.skipUnless(DEBUG.is_file(), "requires saved fb_debug_last.html")
class TestLiveDebugHtml(unittest.TestCase):
    def test_debug_html_yields_post(self) -> None:
        html = DEBUG.read_text(encoding="utf-8")
        post = parse_top_post_from_html(html, PROFILE)
        self.assertIsNotNone(post)
        assert post is not None
        self.assertGreater(len(post.text), 20)
        self.assertNotIn("comment_id", post.permalink.lower())
