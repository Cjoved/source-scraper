import os
import unittest
from unittest.mock import patch

from src.scraper.fb_config import load_fb_page_config


class TestFbConfig(unittest.TestCase):
    def test_defaults(self) -> None:
        env = {
            "FB_PROFILE_URL": "https://www.facebook.com/liezl.p.aquino",
            "FB_EMAIL": "test@example.com",
            "FB_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = load_fb_page_config()
        self.assertEqual(cfg.profile_url, env["FB_PROFILE_URL"])
        self.assertEqual(cfg.email, "test@example.com")
        self.assertTrue(cfg.logout_after)
        self.assertTrue(cfg.keep_images)
        self.assertTrue(cfg.download_images)
        self.assertTrue(cfg.profile_use_all_tab)
        self.assertFalse(cfg.debug_save_html)
        self.assertEqual(cfg.scrape_mode, "latest")
        self.assertEqual(cfg.scrape_timezone, "Asia/Manila")
        self.assertGreaterEqual(cfg.max_posts_per_run, 5)
        self.assertEqual(cfg.scrapling_mode, "stealth")
        self.assertGreaterEqual(cfg.login_delay_min, 1.0)
        self.assertGreaterEqual(cfg.login_delay_max, cfg.login_delay_min)
        self.assertGreaterEqual(cfg.login_typing_delay_ms, 50)
        self.assertIn("fb_liezl_checkpoint.json", str(cfg.checkpoint_path))
