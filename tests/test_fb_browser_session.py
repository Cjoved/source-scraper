import unittest

from src.scraper.clients.fb_browser_session import profile_posts_url, profile_scrape_url


class TestProfilePostsUrl(unittest.TestCase):
    def test_appends_posts(self) -> None:
        url = profile_posts_url("https://www.facebook.com/liezl.p.aquino")
        self.assertEqual(url, "https://www.facebook.com/liezl.p.aquino/posts")

    def test_no_double_posts(self) -> None:
        url = profile_posts_url("https://www.facebook.com/liezl.p.aquino/posts")
        self.assertEqual(url, "https://www.facebook.com/liezl.p.aquino/posts")


class TestProfileScrapeUrl(unittest.TestCase):
    def test_all_tab_uses_profile_root(self) -> None:
        url = profile_scrape_url("https://www.facebook.com/liezl.p.aquino", use_all_tab=True)
        self.assertEqual(url, "https://www.facebook.com/liezl.p.aquino")

    def test_all_tab_strips_posts_suffix(self) -> None:
        url = profile_scrape_url(
            "https://www.facebook.com/liezl.p.aquino/posts", use_all_tab=True
        )
        self.assertEqual(url, "https://www.facebook.com/liezl.p.aquino")

    def test_posts_tab_uses_posts_path(self) -> None:
        url = profile_scrape_url("https://www.facebook.com/liezl.p.aquino", use_all_tab=False)
        self.assertEqual(url, "https://www.facebook.com/liezl.p.aquino/posts")
