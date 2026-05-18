import unittest

from src.models.fb_model import FbTopPost
from src.scraper.parsers.fb_post_dates import (
    parse_hours_ago,
    post_hours_ago,
    post_in_daily_window,
    post_too_old_for_daily_feed,
)


def _post(**kwargs: object) -> FbTopPost:
    defaults = {
        "post_id": "x",
        "permalink": "https://www.facebook.com/liezl.p.aquino/posts/pfbidX",
        "text": "test",
        "image_urls": (),
    }
    defaults.update(kwargs)
    return FbTopPost(**defaults)  # type: ignore[arg-type]


class TestParseHoursAgo(unittest.TestCase):
    def test_compact_hour_labels(self) -> None:
        self.assertEqual(parse_hours_ago("1h"), 1.0)
        self.assertEqual(parse_hours_ago("2h"), 2.0)
        self.assertEqual(parse_hours_ago("23h"), 23.0)

    def test_minutes(self) -> None:
        self.assertLess(parse_hours_ago("45m"), 1.0)

    def test_day_is_outside_window(self) -> None:
        self.assertEqual(parse_hours_ago("1d"), 24.0)
        self.assertEqual(parse_hours_ago("2d"), 48.0)


class TestDailyWindow(unittest.TestCase):
    def test_1h_and_23h_in_window(self) -> None:
        self.assertTrue(post_in_daily_window(_post(posted_at="1h"), "Asia/Manila", max_hours=23))
        self.assertTrue(post_in_daily_window(_post(posted_at="23h"), "Asia/Manila", max_hours=23))

    def test_24h_outside_window(self) -> None:
        self.assertFalse(post_in_daily_window(_post(posted_at="1d"), "Asia/Manila", max_hours=23))

    def test_yesterday_too_old(self) -> None:
        self.assertTrue(post_too_old_for_daily_feed(_post(posted_at="yesterday"), "Asia/Manila", max_hours=23))

    def test_stop_at_24h_equivalent(self) -> None:
        post = _post(posted_at="24h")
        hours = post_hours_ago(post, "Asia/Manila")
        self.assertIsNotNone(hours)
        if hours is not None and hours > 23:
            self.assertTrue(post_too_old_for_daily_feed(post, "Asia/Manila", max_hours=23))
