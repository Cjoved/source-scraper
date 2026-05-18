"""Typed env-backed settings for Facebook profile scrape."""

from __future__ import annotations

import os
from pathlib import Path

from src.models.fb_model import FbPageConfig
from src.services.config import data_path


def _truthy(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("true", "1", "yes")


def load_fb_page_config() -> FbPageConfig:
    profile_url = (os.getenv("FB_PROFILE_URL") or "").strip()
    if not profile_url:
        profile_url = "https://www.facebook.com/liezl.p.aquino"

    mode = (os.getenv("FB_SCRAPLING_MODE") or "stealth").strip().lower()
    headless = os.getenv("FB_HEADLESS", "true").strip().lower() != "false"

    scrape_mode = (os.getenv("FB_SCRAPE_MODE") or "latest").strip().lower()
    if scrape_mode not in ("latest", "daily"):
        scrape_mode = "latest"

    return FbPageConfig(
        profile_url=profile_url,
        email=(os.getenv("FB_EMAIL") or "").strip(),
        password=(os.getenv("FB_PASSWORD") or "").strip(),
        scrapling_mode=mode,
        scrape_mode=scrape_mode,
        scrape_timezone=(os.getenv("FB_SCRAPE_TIMEZONE") or "Asia/Manila").strip(),
        daily_max_age_hours=int(os.getenv("FB_DAILY_MAX_AGE_HOURS", "23")),
        max_posts_per_run=int(os.getenv("FB_MAX_POSTS_PER_RUN", "20")),
        daily_scroll_passes=int(os.getenv("FB_DAILY_SCROLL_PASSES", "6")),
        headless=headless,
        profile_use_all_tab=_truthy("FB_PROFILE_USE_ALL_TAB", "true"),
        debug_save_html=_truthy("FB_DEBUG_SAVE_HTML", "false"),
        js_settle_seconds=float(os.getenv("FB_JS_SETTLE_SECONDS", "10")),
        login_delay_min=float(os.getenv("FB_LOGIN_DELAY_MIN", "1.5")),
        login_delay_max=float(os.getenv("FB_LOGIN_DELAY_MAX", "3.5")),
        login_typing_delay_ms=int(os.getenv("FB_LOGIN_TYPING_DELAY_MS", "85")),
        login_page_wait=float(os.getenv("FB_LOGIN_PAGE_WAIT", "2.5")),
        login_after_submit_wait=float(os.getenv("FB_LOGIN_AFTER_SUBMIT_WAIT", "4.0")),
        logout_after=_truthy("FB_LOGOUT_AFTER", "true"),
        keep_images=_truthy("FB_KEEP_IMAGES", "true"),
        download_images=_truthy("FB_DOWNLOAD_IMAGES", "true"),
        max_images_per_post=int(os.getenv("FB_MAX_IMAGES_PER_POST", "5")),
        max_image_bytes=int(os.getenv("FB_MAX_IMAGE_BYTES", "15728640")),
        checkpoint_path=_path_env("FB_CHECKPOINT_PATH", "checkpoints", "fb_liezl_checkpoint.json"),
        output_jsonl_path=_path_env("FB_OUTPUT_JSONL", "prism_processed", "fb_liezl_posts.jsonl"),
        images_dir=_path_env("FB_IMAGES_DIR", "prism_processed", "fb_liezl_images"),
    )


def _path_env(env_name: str, *parts: str) -> Path:
    from pathlib import Path

    override = (os.getenv(env_name) or "").strip()
    if override:
        return Path(override)
    return data_path(*parts)
