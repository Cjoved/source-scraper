"""Download Facebook post images using the authenticated browser session."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

import requests

from src.models.fb_model import FbPageConfig
from src.services.config import PROJECT_ROOT


def repo_relative_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _cookies_from_session(session: Any) -> dict[str, str]:
    context = getattr(session, "context", None)
    if context is None:
        return {}
    try:
        jar = context.cookies()
        return {c["name"]: c["value"] for c in jar if c.get("name") and c.get("value")}
    except Exception:
        return {}


def _extension_from_content_type(content_type: str | None, url: str) -> str:
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return ".jpg" if ext == ".jpe" else ext
    lower = url.lower()
    for cand in (".jpg", ".jpeg", ".png", ".webp"):
        if cand in lower:
            return ".jpg" if cand == ".jpeg" else cand
    return ".jpg"


def download_post_images(
    session: Any,
    cfg: FbPageConfig,
    post_id: str,
    image_urls: tuple[str, ...],
) -> list[Path]:
    if not cfg.download_images or not image_urls:
        return []

    cfg.images_dir.mkdir(parents=True, exist_ok=True)
    cookies = _cookies_from_session(session)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.facebook.com/",
    }
    saved: list[Path] = []
    safe_id = post_id.replace("/", "_")[:80]

    for idx, url in enumerate(image_urls[: cfg.max_images_per_post]):
        dest = cfg.images_dir / f"{safe_id}_{idx}.jpg"
        try:
            resp = requests.get(url, cookies=cookies, headers=headers, timeout=60, stream=True)
            resp.raise_for_status()
            content = b""
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    content += chunk
                    if len(content) > cfg.max_image_bytes:
                        break
            if not content:
                continue
            ext = _extension_from_content_type(resp.headers.get("Content-Type"), url)
            dest = dest.with_suffix(ext)
            dest.write_bytes(content[: cfg.max_image_bytes])
            saved.append(dest)
        except Exception:
            continue

    return saved
