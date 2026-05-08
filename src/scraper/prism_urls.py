"""Seed URLs and PRiSM /dataproducts → wp-dynamicreports normalization."""

from __future__ import annotations

import re
import urllib.parse


def parse_seed_urls(raw: str) -> list[str]:
    parts = re.split(r"[\s,]+", raw)
    return [p.strip() for p in parts if p.strip().startswith(("http://", "https://"))]


def normalize_prism_target_url(url: str, *, rewrite_dataproducts: bool = True) -> str:
    if not rewrite_dataproducts:
        return url
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return url
    host = (p.netloc or "").lower()
    path = (p.path or "").lower().rstrip("/")
    if "prism.philrice.gov.ph" not in host:
        return url
    if path.endswith("/dataproducts") or "/dataproducts/" in path or path == "/dataproducts":
        return urllib.parse.urlunparse(
            (
                p.scheme or "https",
                "prism.philrice.gov.ph",
                "/wp-dynamicreports",
                "",
                "",
                "",
            )
        )
    return url


def is_prism_dynamic_app(url: str) -> bool:
    u = url.lower()
    return "prism.philrice.gov.ph" in u and "wp-dynamicreports" in u
