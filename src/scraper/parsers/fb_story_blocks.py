"""Extract profile posts from Facebook story feed blocks (not role=article comments)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from src.models.fb_model import FbTopPost
from src.scraper.parsers.fb_feed_helpers import (
    has_story_text_signals,
    is_comment_ui_article,
    other_posts_labels,
)
from src.scraper.parsers.fb_post_urls import (
    clean_permalink,
    extract_post_id_from_href,
    safe_post_id,
)
from src.scraper.parsers.fb_profile_posts import (
    _base_url,
    _collect_image_urls,
    _looks_like_post_image,
    _profile_slug,
)

_PFBID_PATH = re.compile(r"/posts/pfbid[\w]+", re.I)
_REL_TIME_IN_TEXT = re.compile(
    r"\b(\d+[hdmws]|\d+\s*(min|mins|minutes?|hr|hrs|hours?|days?)|just now|yesterday)\b",
    re.I,
)

_STORY_DESCRIPTION = '[data-ad-rendering-role="description"]'
_STORY_MESSAGE = '[data-ad-rendering-role="story_message"]'
_STORY_TITLE = '[data-ad-rendering-role="title"]'


def _permalink_matches_profile(permalink: str, slug: str) -> bool:
    if not slug:
        return True
    return slug.lower() in permalink.lower()


def resolve_post_permalink(href: str, base: str) -> str | None:
    """Parent post URL even when the raw href includes comment_id."""
    if not href:
        return None
    return clean_permalink(href.replace("&amp;", "&"), base)


def find_permalink_in_fragment(fragment: str, base: str) -> str | None:
    for href in re.findall(r"""href=["']([^"']+)["']""", fragment):
        clean = resolve_post_permalink(href, base)
        if clean:
            return clean
    match = _PFBID_PATH.search(fragment)
    if match:
        return urljoin(base, match.group(0))
    return None


def _story_text_from_root(root: Any) -> str:
    for sel in (_STORY_MESSAGE, _STORY_DESCRIPTION, _STORY_TITLE):
        nodes = root.css(sel)
        if not nodes:
            continue
        text = "\n".join(
            " ".join(n.css("::text").getall()).strip() for n in nodes if n.css("::text").getall()
        ).strip()
        if len(text) >= 15:
            return text
    chunks: list[str] = []
    for node in root.css('[dir="auto"]'):
        text = " ".join(t.strip() for t in node.css("::text").getall() if t and str(t).strip())
        if text and len(text) >= 20 and text not in chunks:
            chunks.append(text)
    return "\n".join(chunks).strip()


def _story_has_timestamp(root: Any, text: str) -> bool:
    if root.css("time[datetime]"):
        return True
    if _REL_TIME_IN_TEXT.search(text):
        return True
    for a in root.css("a[href]"):
        label = " ".join(a.css("::text").getall()).strip()
        if label and _REL_TIME_IN_TEXT.search(label):
            return True
    return bool(root.css('[data-ad-rendering-role="meta"]'))


def _is_valid_story_text(text: str) -> bool:
    if not text or is_comment_ui_article(text):
        return False
    if "like reply" in text.lower() and len(text) < 200:
        return False
    return len(text) >= 25 or "#" in text or has_story_text_signals(text)


def build_post_from_story_root(root: Any, profile_url: str, *, html_fragment: str = "") -> FbTopPost | None:
    base = _base_url(profile_url)
    slug = _profile_slug(profile_url)
    text = _story_text_from_root(root)
    if not _is_valid_story_text(text):
        return None

    fragment = html_fragment or (root.get() or "")
    permalink = find_permalink_in_fragment(fragment, base)
    if not permalink or not _permalink_matches_profile(permalink, slug):
        return None

    if not _story_has_timestamp(root, text) and not _collect_image_urls(root):
        return None

    post_id = extract_post_id_from_href(permalink) or safe_post_id(permalink)
    posted_at: str | None = None
    posted_iso: str | None = None
    for t in root.css("time[datetime]"):
        posted_iso = (t.attrib.get("datetime") or "").strip() or None
        if posted_iso:
            posted_at = posted_iso
            break
    if not posted_at:
        match = _REL_TIME_IN_TEXT.search(text)
        if match:
            posted_at = match.group(1)

    image_urls = tuple(_collect_image_urls(root))
    return FbTopPost(
        post_id=post_id,
        permalink=permalink,
        text=text,
        image_urls=image_urls,
        posted_at=posted_at,
        posted_at_iso=posted_iso,
    )


def _html_story_roots_after_other_posts(page: Any) -> list[Any]:
    roots: list[Any] = []
    for label in other_posts_labels():
        markers = page.xpath(
            f'//*[contains(normalize-space(.), "{label}")][not(ancestor::*[@role="complementary"])]'
        )
        for marker in markers:
            for node in marker.xpath("following::*[@aria-posinset][1]"):
                roots.append(node)
            for node in marker.xpath(
                f"following::*{_STORY_DESCRIPTION}[1]/ancestor::*[@aria-posinset][1]"
            ):
                roots.append(node)
            for node in marker.xpath(f"following::*{_STORY_DESCRIPTION}[1]"):
                roots.append(node)
    return roots


def parse_story_after_other_posts(page: Any, profile_url: str) -> FbTopPost | None:
    seen: set[int] = set()
    for root in _html_story_roots_after_other_posts(page):
        rid = id(root)
        if rid in seen:
            continue
        seen.add(rid)
        post = build_post_from_story_root(root, profile_url)
        if post is not None:
            return post
    return None
