"""
Shared scraper helpers: URL normalization, checkpoint load/save, safe filenames.
"""
import json
import os
import re
import urllib.parse
from datetime import datetime
from typing import Any


def normalize_url(href: str, base: str) -> str | None:
    """Make absolute URL; return None if href is empty."""
    if not href or not href.strip():
        return None
    href = href.strip()
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("//"):
        return "https:" + href
    return urllib.parse.urljoin(base, href)


def load_checkpoint(path: str, default: Any = None) -> Any:
    """Load JSON checkpoint; return default if missing or invalid."""
    if default is None:
        default = {"scraped_urls": [], "downloaded_urls": []}
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_checkpoint(path: str, data: dict, add_updated: bool = True) -> None:
    """Write checkpoint JSON. Optionally set data['updated'] to now."""
    if add_updated:
        data = {**data, "updated": datetime.now().isoformat()}
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def safe_filename_from_url(url: str, max_len: int = 180, suffix: str = ".pdf") -> str:
    """Safe filename from URL path; ensure suffix if needed."""
    try:
        parsed = urllib.parse.urlparse(url)
        name = (parsed.path or "").split("/")[-1] or "download"
    except Exception:
        name = "download"
    name = re.sub(r"[^\w\-_.]", "_", name)
    if suffix and not name.lower().endswith(suffix.lower()):
        name = name + suffix
    return name[: max_len + len(suffix)]
