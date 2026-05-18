"""Facebook post URL helpers — reject comment links, normalize permalinks."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse

_POST_ID_PATTERNS = (
    re.compile(r"/posts/(?:pfbid)?([^/?#]+)", re.I),
    re.compile(r"story_fbid=(\d+)", re.I),
    re.compile(r"(pfbid[\w]+)", re.I),
    re.compile(r"multi_permalinks=(\d+)", re.I),
    re.compile(r"/permalink/(\d+)", re.I),
)

_COMMENT_QUERY_KEYS = frozenset(
    {
        "comment_id",
        "reply_comment_id",
        "comment_tracking",
        "ft_ent_identifier",
    }
)


def safe_post_id(raw: str) -> str:
    cleaned = re.sub(r"[^\w.\-]", "_", raw.strip())[:120]
    return cleaned or "unknown_post"


def extract_post_id_from_href(href: str) -> str | None:
    if not href:
        return None
    for pattern in _POST_ID_PATTERNS:
        m = pattern.search(href)
        if m:
            return safe_post_id(m.group(1))
    return None


def is_comment_href(href: str) -> bool:
    lower = href.lower()
    if any(key in lower for key in _COMMENT_QUERY_KEYS):
        return True
    if "/comment/" in lower:
        return True
    return False


def has_post_path(href: str) -> bool:
    if not href:
        return False
    lower = href.lower()
    if "/comment/" in lower:
        return False
    return "/posts/" in lower or "pfbid" in lower or "story_fbid" in lower


def is_post_permalink_href(href: str) -> bool:
    return has_post_path(href) and not is_comment_href(href)


def clean_permalink(href: str, base_url: str) -> str | None:
    full = urljoin(base_url, href)
    if extract_post_id_from_href(full) is None:
        return None
    parsed = urlparse(full)
    path_lower = parsed.path.lower()
    if "/posts/" not in path_lower and "pfbid" not in path_lower and "/permalink/" not in path_lower:
        return None
    if "/comment/" in path_lower:
        return None
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
