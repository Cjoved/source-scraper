import unittest

from src.scraper.parsers.fb_feed_helpers import (
    feed_start_index,
    has_story_text_signals,
    is_comment_ui_article,
    is_pinned_article_text,
    is_sidebar_noise,
    looks_like_relative_time,
)


class TestFeedHelpers(unittest.TestCase):
    def test_skip_pinned_when_label(self) -> None:
        self.assertEqual(feed_start_index(True), 1)
        self.assertEqual(feed_start_index(False), 0)

    def test_sidebar_communities(self) -> None:
        text = "Communities\nLiezl P Aquino Subscriber hub"
        self.assertTrue(is_sidebar_noise(text))

    def test_pinned_text(self) -> None:
        self.assertTrue(is_pinned_article_text("Pinned post\nLiezl P Aquino\nPart3 Towns"))

    def test_real_post_not_sidebar(self) -> None:
        text = "Liezl P Aquino\nPart3 Towns and Cities to Receive Seed"
        self.assertFalse(is_sidebar_noise(text))
        self.assertFalse(is_pinned_article_text(text))

    def test_comment_composer(self) -> None:
        self.assertTrue(is_comment_ui_article("Write a comment…\nLiezl P Aquino"))

    def test_comment_reply_pattern(self) -> None:
        text = "Derlina De Vera\nThank you for the update!"
        self.assertTrue(is_comment_ui_article(text))

    def test_story_post_not_comment(self) -> None:
        text = "P10,125 Tulong Pinansyal para sa mga magsasaka #MAGSASAKA"
        self.assertFalse(is_comment_ui_article(text))

    def test_relative_time_labels(self) -> None:
        self.assertTrue(looks_like_relative_time("1h"))
        self.assertTrue(looks_like_relative_time("May 12"))
        self.assertFalse(looks_like_relative_time("Like"))

    def test_story_text_signals(self) -> None:
        self.assertTrue(has_story_text_signals("P10,125 Tulong Pinansyal #DSWD"))
