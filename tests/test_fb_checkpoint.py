import unittest

from src.scraper.spiders.fb_checkpoint import build_checkpoint_update, should_persist_post


class TestFbCheckpoint(unittest.TestCase):
    def test_new_post_when_empty_checkpoint(self) -> None:
        self.assertTrue(should_persist_post(None, "abc"))

    def test_skip_same_post(self) -> None:
        self.assertFalse(should_persist_post("abc", "abc"))

    def test_persist_different_post(self) -> None:
        self.assertTrue(should_persist_post("abc", "xyz"))

    def test_build_checkpoint(self) -> None:
        ck = build_checkpoint_update(
            "https://www.facebook.com/liezl.p.aquino",
            "post1",
            "May 18, 2026",
            "2026-05-18T17:00:00",
        )
        self.assertEqual(ck["last_post_id"], "post1")
        self.assertEqual(ck["profile_url"], "https://www.facebook.com/liezl.p.aquino")
