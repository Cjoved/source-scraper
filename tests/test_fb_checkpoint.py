import unittest

from src.scraper.spiders.fb_checkpoint import (
    build_checkpoint_update,
    load_seen_post_ids,
    merge_seen_ids,
    should_persist_post,
    should_persist_post_id,
)


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
            seen_post_ids={"post1", "post0"},
        )
        self.assertEqual(ck["last_post_id"], "post1")
        self.assertEqual(ck["profile_url"], "https://www.facebook.com/liezl.p.aquino")
        self.assertIn("post1", ck["seen_post_ids"])

    def test_seen_post_ids_dedupe(self) -> None:
        seen = load_seen_post_ids({"seen_post_ids": ["a"], "last_post_id": "b"})
        self.assertEqual(seen, {"a", "b"})
        self.assertFalse(should_persist_post_id(seen, "a"))
        self.assertTrue(should_persist_post_id(seen, "c"))
        merged = merge_seen_ids(seen, ["c", "d"])
        self.assertEqual(merged, {"a", "b", "c", "d"})
