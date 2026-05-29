"""
Shared scraper helpers: URL normalization, checkpoint load/save, safe filenames.
"""
import re
import urllib.parse
from pathlib import Path
from typing import Any

from src.services.checkpoint import load_checkpoint as _load_checkpoint
from src.services.checkpoint import save_checkpoint as _save_checkpoint


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


def load_checkpoint(path: str | Path, default: Any = None) -> Any:
    """Load JSON checkpoint; return default if missing or invalid."""
    return _load_checkpoint(path, default)


def save_checkpoint(path: str | Path, data: dict, add_updated: bool = True) -> None:
    """Write checkpoint JSON. Optionally set data['updated'] to now."""
    _save_checkpoint(path, data, add_updated=add_updated)


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
