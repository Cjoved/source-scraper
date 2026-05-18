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
from src.scraper.parsers.fb_post_dates import parse_hours_ago
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
_COMPACT_HM = re.compile(r"^(\d+)([hdm])$", re.I)

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


def _story_posted_label_from_root(root: Any) -> str | None:
    """FB shows age beside the name: Liezl P Aquino · 2h · Public."""
    for meta in root.css('[data-ad-rendering-role="meta"]'):
        raw = " ".join(meta.css("::text").getall()).strip()
        for piece in re.split(r"[·•|]", raw):
            piece = piece.strip()
            if not piece:
                continue
            if parse_hours_ago(piece) is not None:
                return piece
            if _COMPACT_HM.match(piece):
                return piece
    for abbr in root.css("abbr[title], abbr[aria-label]"):
        val = (abbr.attrib.get("title") or abbr.attrib.get("aria-label") or "").strip()
        if val and parse_hours_ago(val) is not None:
            return val
    for anchor in root.css('a[href*="/posts/"], a[href*="pfbid"]'):
        label = " ".join(anchor.css("::text").getall()).strip()
        if label and parse_hours_ago(label) is not None:
            return label
        if label and _COMPACT_HM.match(label):
            return label
    for anchor in root.css("a[href]"):
        label = " ".join(anchor.css("::text").getall()).strip()
        if label and _COMPACT_HM.match(label):
            return label
    match = _REL_TIME_IN_TEXT.search(
        " ".join(root.css('[data-ad-rendering-role="meta"] ::text').getall())
    )
    if match:
        return match.group(1)
    return None


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
        posted_at = _story_posted_label_from_root(root)
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


def _append_unique_root(roots: list[Any], seen_nodes: set[int], node: Any) -> None:
    rid = id(node)
    if rid in seen_nodes:
        return
    seen_nodes.add(rid)
    roots.append(node)


def _html_story_roots_after_other_posts(page: Any) -> list[Any]:
    roots: list[Any] = []
    seen_nodes: set[int] = set()
    for label in other_posts_labels():
        markers = page.xpath(
            f'//*[contains(normalize-space(.), "{label}")][not(ancestor::*[@role="complementary"])]'
        )
        for marker in markers:
            for node in marker.xpath("following::*[@aria-posinset]"):
                _append_unique_root(roots, seen_nodes, node)
            for desc in marker.xpath(
                f"following::*{_STORY_MESSAGE} | following::*{_STORY_DESCRIPTION}"
            ):
                ancestors = desc.xpath("ancestor::*[@aria-posinset][1]")
                if ancestors:
                    _append_unique_root(roots, seen_nodes, ancestors[0])
                else:
                    _append_unique_root(roots, seen_nodes, desc)
    return roots


def parse_stories_after_other_posts(
    page: Any,
    profile_url: str,
    *,
    max_posts: int = 20,
) -> list[FbTopPost]:
    posts: list[FbTopPost] = []
    seen_ids: set[str] = set()
    for root in _html_story_roots_after_other_posts(page):
        post = build_post_from_story_root(root, profile_url)
        if post is None or post.post_id in seen_ids:
            continue
        seen_ids.add(post.post_id)
        posts.append(post)
        if len(posts) >= max_posts:
            break
    return posts


def parse_story_after_other_posts(page: Any, profile_url: str) -> FbTopPost | None:
    posts = parse_stories_after_other_posts(page, profile_url, max_posts=1)
    return posts[0] if posts else None
