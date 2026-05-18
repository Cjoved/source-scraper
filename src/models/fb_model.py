from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FbPageConfig:
    profile_url: str
    email: str
    password: str
    scrapling_mode: str
    scrape_mode: str
    scrape_timezone: str
    daily_max_age_hours: int
    max_posts_per_run: int
    daily_scroll_passes: int
    headless: bool
    profile_use_all_tab: bool
    debug_save_html: bool
    js_settle_seconds: float
    login_delay_min: float
    login_delay_max: float
    login_typing_delay_ms: int
    login_page_wait: float
    login_after_submit_wait: float
    logout_after: bool
    keep_images: bool
    download_images: bool
    max_images_per_post: int
    max_image_bytes: int
    checkpoint_path: Path
    output_jsonl_path: Path
    images_dir: Path


@dataclass(frozen=True)
class FbTopPost:
    post_id: str
    permalink: str
    text: str
    image_urls: tuple[str, ...]
    posted_at: str | None = None
    posted_at_iso: str | None = None
