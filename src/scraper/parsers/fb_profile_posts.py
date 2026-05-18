"""Parse the latest post from a Facebook profile timeline HTML."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from src.models.fb_model import FbTopPost
from src.scraper.parsers.fb_feed_helpers import (
    has_story_text_signals,
    is_comment_ui_article,
    is_pinned_article_text,
    is_sidebar_noise,
    looks_like_relative_time,
    other_posts_labels,
)
from src.scraper.parsers.fb_post_urls import (
    clean_permalink,
    extract_post_id_from_href,
    is_comment_href,
    safe_post_id,
)

_FB_CDN_HINTS = ("scontent", "fbcdn.net", "external.")
_SKIP_IMG_HINTS = (
    "emoji",
    "static_xx",
    "rsrc.php",
    "safe_image",
    "profile_pic",
    "sticker",
    "/v4/yh/r/",
)


def _is_post_href(href: str) -> bool:
    if is_comment_href(href):
        return False
    lower = href.lower()
    return any(
        token in lower
        for token in ("/posts/", "pfbid", "story_fbid", "multi_permalinks", "/permalink/")
    )


def _best_image_url(src: str | None, srcset: str | None) -> str | None:
    if srcset:
        parts = [p.strip().split()[0] for p in srcset.split(",") if p.strip()]
        if parts:
            return parts[-1]
    if src and _looks_like_post_image(src):
        return src
    return None


def _looks_like_post_image(url: str) -> bool:
    lower = url.lower()
    if any(h in lower for h in _SKIP_IMG_HINTS):
        return False
    return any(h in lower for h in _FB_CDN_HINTS) or lower.endswith((".jpg", ".jpeg", ".png", ".webp"))


def _collect_image_urls(container: Any) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []

    for img in container.css("img"):
        src = (img.attrib.get("src") or "").strip()
        srcset = (img.attrib.get("srcset") or "").strip()
        best = _best_image_url(src, srcset)
        if best and best not in seen and _looks_like_post_image(best):
            seen.add(best)
            urls.append(best)
    return urls


def _base_url(profile_url: str) -> str:
    if profile_url.startswith("http"):
        return profile_url.rstrip("/")
    return f"https://www.facebook.com{profile_url}".rstrip("/")


def _find_post_containers(page: Any) -> list[Any]:
    for sel in (
        '[role="main"] [role="article"]',
        '[data-pagelet="ProfileTimeline"] [role="article"]',
        '[role="article"]',
    ):
        nodes = page.css(sel)
        if nodes:
            return list(nodes)
    return []


def _container_text(container: Any) -> str:
    return " ".join(t.strip() for t in container.css("::text").getall() if t and str(t).strip())


def _is_pinned_container(container: Any) -> bool:
    return is_pinned_article_text(_container_text(container))


def _is_sidebar_container(container: Any) -> bool:
    return is_sidebar_noise(_container_text(container))


def _is_invalid_feed_container(container: Any) -> bool:
    text = _container_text(container)
    if not text:
        return True
    if _is_sidebar_container(container) or _is_pinned_container(container):
        return True
    if is_comment_ui_article(text):
        return True
    return False


def _profile_slug(profile_url: str) -> str:
    path = urlparse(_base_url(profile_url)).path.strip("/")
    return path.split("/")[0] if path else ""


def _permalink_matches_profile(permalink: str, slug: str) -> bool:
    if not slug:
        return True
    return slug.lower() in permalink.lower()


def _container_has_post_timestamp(container: Any) -> bool:
    for t in container.css("time[datetime]"):
        parent_href = ""
        for a in t.xpath("ancestor::a[@href][1]"):
            parent_href = (a.attrib.get("href") or "").strip()
            break
        if parent_href and not is_comment_href(parent_href):
            return True
        if not parent_href and (t.attrib.get("datetime") or "").strip():
            return True
    for abbr in container.css('a[href*="/posts/"] abbr, a[href*="pfbid"] abbr'):
        for a in abbr.xpath("ancestor::a[@href][1]"):
            href = (a.attrib.get("href") or "").strip()
            if href and not is_comment_href(href):
                return True
    for a in container.css('a[href*="/posts/"], a[href*="pfbid"]'):
        href = (a.attrib.get("href") or "").strip()
        if not href or is_comment_href(href):
            continue
        label = " ".join(a.css("::text").getall()).strip()
        if looks_like_relative_time(label):
            return True
    return False


def _is_valid_feed_container(container: Any, base: str, slug: str) -> bool:
    if _is_invalid_feed_container(container):
        return False
    permalink, post_id = _find_permalink(container, base)
    if not post_id or not permalink or is_comment_href(permalink):
        return False
    if not _permalink_matches_profile(permalink, slug):
        return False
    if not _container_has_post_timestamp(container):
        return False
    text = _extract_caption(container)
    has_feed_image = bool(_collect_image_urls(container))
    if has_feed_image or len(text) >= 25 or "#" in text or has_story_text_signals(text):
        return True
    return False


def _first_article_after_other_posts(page: Any, base: str, slug: str) -> Any | None:
    for label in other_posts_labels():
        markers = page.xpath(
            f'//*[contains(normalize-space(.), "{label}")][not(ancestor::*[@role="complementary"])]'
        )
        for marker in markers:
            for article in marker.xpath('following::*[@role="article"]'):
                if _is_valid_feed_container(article, base, slug):
                    return article
    return None


def _main_feed_has_pinned_label(page: Any) -> bool:
    for sel in ('[role="main"]', "body"):
        nodes = page.css(sel)
        if not nodes:
            continue
        text = " ".join(t.strip() for t in nodes[0].css("::text").getall()[:40] if t and str(t).strip()).lower()
        if "pinned post" in text[:400]:
            return True
    return False


def _find_post_container(
    page: Any,
    profile_url: str,
    *,
    skip_pinned: bool = True,
) -> Any | None:
    base = _base_url(profile_url)
    slug = _profile_slug(profile_url)

    after_other = _first_article_after_other_posts(page, base, slug)
    if after_other is not None:
        return after_other

    containers = _find_post_containers(page)
    has_pinned = _main_feed_has_pinned_label(page) or (
        bool(containers) and _is_pinned_container(containers[0])
    )
    has_other_marker = any(
        page.xpath(f'//*[contains(normalize-space(.), "{label}")]') for label in other_posts_labels()
    )
    if has_other_marker:
        return None

    start = 1 if skip_pinned and has_pinned and containers else 0
    for container in containers[start:]:
        if _is_valid_feed_container(container, base, slug):
            return container
    return None


def _find_permalink_in_root(root: Any, base_url: str) -> tuple[str | None, str | None]:
    from src.scraper.parsers.fb_story_blocks import find_permalink_in_fragment, resolve_post_permalink

    fragment = root.get() or ""
    found = find_permalink_in_fragment(fragment, base_url)
    if found:
        return found, extract_post_id_from_href(found)

    for a in root.css("a[href]"):
        href = (a.attrib.get("href") or "").strip()
        clean = resolve_post_permalink(href, base_url)
        if not clean:
            continue
        if not _is_post_href(href) and "pfbid" not in href.lower():
            continue
        post_id = extract_post_id_from_href(clean)
        if post_id:
            return clean, post_id
    return None, None


def _find_permalink(container: Any, base_url: str) -> tuple[str | None, str | None]:
    found = _find_permalink_in_root(container, base_url)
    if found[0]:
        return found
    from src.scraper.parsers.fb_story_blocks import resolve_post_permalink

    for a in container.css('a[href*="/posts/"], a[href*="pfbid"]'):
        href = (a.attrib.get("href") or "").strip()
        clean = resolve_post_permalink(href, base_url)
        if not clean:
            continue
        post_id = extract_post_id_from_href(clean)
        if post_id:
            return clean, post_id
    return None, None


def _extract_posted_at(container: Any) -> tuple[str | None, str | None]:
    for t in container.css("time[datetime]"):
        iso_val = (t.attrib.get("datetime") or "").strip()
        if iso_val:
            label = " ".join(t.css("::text").getall()).strip()
            return label or iso_val, iso_val
    for abbr in container.css('a[href*="/posts/"] abbr, a[role="link"][href*="/posts/"] abbr'):
        val = (abbr.attrib.get("title") or abbr.attrib.get("aria-label") or "").strip()
        if val:
            return val, None
    for abbr in container.css("abbr"):
        val = (abbr.attrib.get("title") or abbr.attrib.get("aria-label") or "").strip()
        if val:
            return val, None
    return None, None


def _extract_caption(container: Any) -> str:
    chunks: list[str] = []
    skip_fragments = ("see more", "see less", "rate this translation", "pinned post")
    for node in container.css('[dir="auto"]'):
        text = " ".join(t.strip() for t in node.css("::text").getall() if t and str(t).strip())
        if not text:
            continue
        lower = text.lower()
        if any(s in lower for s in skip_fragments):
            continue
        if text not in chunks:
            chunks.append(text)
    return "\n".join(chunks).strip()


def _parse_from_page_links(page: Any, base: str) -> FbTopPost | None:
    permalink, post_id = _find_permalink_in_root(page, base)
    if not post_id:
        return None

    image_urls: list[str] = _collect_image_urls(page)
    text = ""
    posted_at: str | None = None
    posted_iso: str | None = None

    for sel in ('[role="article"]',):
        articles = page.css(sel)
        if articles:
            text = _extract_caption(articles[0])
            posted_label, posted_iso = _extract_posted_at(articles[0])
            posted_at = posted_iso or posted_label
            imgs = _collect_image_urls(articles[0])
            if imgs:
                image_urls = imgs
            break

    if permalink and "comment_id" in permalink.lower():
        clean = clean_permalink(permalink, base)
        permalink = clean or permalink

    return FbTopPost(
        post_id=post_id,
        permalink=permalink or f"{base}/posts/{post_id}",
        text=text,
        image_urls=tuple(image_urls),
        posted_at=posted_at,
        posted_at_iso=posted_iso,
    )


def parse_top_post_from_page(page: Any, profile_url: str) -> FbTopPost | None:
    """Extract the first timeline post from a Scrapling Response / Selector root."""
    from src.scraper.parsers.fb_story_blocks import parse_story_after_other_posts

    story = parse_story_after_other_posts(page, profile_url)
    if story is not None:
        return story

    base = _base_url(profile_url)
    container = _find_post_container(page, profile_url)
    if container is None:
        return _parse_from_page_links(page, base)

    permalink, post_id = _find_permalink(container, base)
    if not post_id:
        fallback = _parse_from_page_links(page, base)
        if fallback:
            return fallback
        post_id = safe_post_id(permalink or "unknown")

    if permalink and "comment_id" in permalink.lower():
        clean = clean_permalink(permalink, base)
        if clean:
            permalink = clean
            post_id = extract_post_id_from_href(permalink) or post_id

    if not permalink:
        parsed = urlparse(base)
        host_base = f"{parsed.scheme}://{parsed.netloc}"
        permalink = f"{host_base}/posts/{post_id}"

    image_urls = tuple(_collect_image_urls(container))
    text = _extract_caption(container)
    posted_label, posted_iso = _extract_posted_at(container)
    posted_at = posted_iso or posted_label

    return FbTopPost(
        post_id=post_id,
        permalink=permalink,
        text=text,
        image_urls=image_urls,
        posted_at=posted_at,
        posted_at_iso=posted_iso,
    )


def parse_top_post_from_html(html: str, profile_url: str) -> FbTopPost | None:
    from parsel import Selector

    return parse_top_post_from_page(Selector(text=html), profile_url)
