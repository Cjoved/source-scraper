"""Extract the first post under 'Other posts' via Playwright."""

from __future__ import annotations

import re
from typing import Any

from src.models.fb_model import FbTopPost
from src.scraper.parsers.fb_feed_helpers import (
    feed_start_index,
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
    has_post_path,
    is_comment_href,
    safe_post_id,
)
from src.scraper.parsers.fb_story_blocks import (
    build_post_from_story_root,
    find_permalink_in_fragment,
    resolve_post_permalink,
)
from src.scraper.parsers.fb_profile_posts import _base_url, _looks_like_post_image

_MESSAGE_SELECTORS = (
    '[data-ad-preview="message"]',
    '[data-ad-comet-preview="message"]',
    '[data-ad-rendering-role="story_message"]',
)

_FEED_ARTICLE_SELECTORS = (
    '[role="main"] [role="article"]',
    '[data-pagelet="ProfileTimeline"] [role="article"]',
    'motion.div div[role="main"] [role="article"]',
)


def _profile_slug(profile_url: str) -> str:
    from urllib.parse import urlparse

    path = urlparse(_base_url(profile_url)).path.strip("/")
    return path.split("/")[0] if path else ""


def _locate_feed_articles(page: Any) -> Any:
    for sel in _FEED_ARTICLE_SELECTORS:
        loc = page.locator(sel)
        if loc.count() > 0:
            return loc
    return page.locator('[role="article"]')


def _page_has_pinned_label(page: Any) -> bool:
    try:
        if page.get_by_text("Pinned post", exact=True).count() > 0:
            return True
        if page.locator('span:has-text("Pinned post")').count() > 0:
            return True
    except Exception:
        pass
    return False


def _scroll_other_posts_marker(page: Any) -> bool:
    for label in other_posts_labels():
        try:
            marker = page.get_by_text(label, exact=False)
            if marker.count() > 0:
                marker.first.scroll_into_view_if_needed(timeout=10_000)
                page.wait_for_timeout(2000)
                return True
        except Exception:
            continue
    return False


def _other_posts_start_index(page: Any, articles: Any, count: int) -> int:
    for label in other_posts_labels():
        try:
            marker = page.get_by_text(label, exact=False)
            if marker.count() == 0:
                continue
            heading_box = marker.first.bounding_box()
            if not heading_box:
                continue
            heading_y = heading_box["y"]
            for i in range(count):
                try:
                    box = articles.nth(i).bounding_box()
                    if box and box["y"] > heading_y:
                        return i
                except Exception:
                    continue
        except Exception:
            continue
    return -1


def _article_after_other_posts_locator(page: Any) -> Any | None:
    for label in other_posts_labels():
        try:
            marker = page.get_by_text(label, exact=False).first
            following = marker.locator("xpath=following::motion.div[@role='article'][1]")
            if following.count() > 0:
                return following
            following = marker.locator("xpath=following::div[@role='article'][1]")
            if following.count() > 0:
                return following
        except Exception:
            continue
    return None


def _article_inner_text(article: Any) -> str:
    try:
        return (article.inner_text(timeout=2_000) or "").strip()
    except Exception:
        return ""


def _anchor_href_from_node(node: Any) -> str:
    try:
        return (
            node.evaluate("el => el.closest('a')?.getAttribute('href') || ''") or ""
        )
    except Exception:
        return ""


def _is_non_comment_post_href(href: str) -> bool:
    return bool(href) and has_post_path(href)


def _has_valid_post_timestamp(article: Any, *, relaxed: bool = False) -> bool:
    try:
        time_anchors = article.locator(
            'a[href*="/posts/"] time[datetime], a[href*="pfbid"] time[datetime]'
        )
        for ti in range(min(time_anchors.count(), 5)):
            try:
                raw_href = _anchor_href_from_node(time_anchors.nth(ti))
                if _is_non_comment_post_href(raw_href):
                    return True
            except Exception:
                continue

        abbr_anchors = article.locator('a[href*="/posts/"] abbr[title], a[href*="pfbid"] abbr[title]')
        for ai in range(min(abbr_anchors.count(), 8)):
            try:
                raw_href = _anchor_href_from_node(abbr_anchors.nth(ai))
                if _is_non_comment_post_href(raw_href):
                    return True
            except Exception:
                continue

        if relaxed:
            for ti in range(min(article.locator("time[datetime]").count(), 8)):
                try:
                    node = article.locator("time[datetime]").nth(ti)
                    if (node.get_attribute("datetime") or "").strip():
                        raw_href = _anchor_href_from_node(node)
                        if not raw_href or not is_comment_href(raw_href):
                            return True
                except Exception:
                    continue

            post_links = article.locator('a[href*="/posts/"], a[href*="pfbid"]')
            for li in range(min(post_links.count(), 12)):
                try:
                    link = post_links.nth(li)
                    href = link.get_attribute("href") or ""
                    if not _is_non_comment_post_href(href):
                        continue
                    label = (link.inner_text(timeout=800) or "").strip()
                    if looks_like_relative_time(label):
                        return True
                    title = (link.get_attribute("aria-label") or "").strip()
                    if looks_like_relative_time(title):
                        return True
                except Exception:
                    continue
    except Exception:
        pass
    return False


def _permalink_matches_profile(permalink: str, slug: str) -> bool:
    if not slug:
        return True
    return slug.lower() in permalink.lower()


def _has_story_content(article: Any, text: str, caption: str) -> bool:
    if bool(_extract_images(article)):
        return True
    body = caption or text
    if len(body) >= 25:
        return True
    if "#" in body or has_story_text_signals(body):
        return True
    for sel in _MESSAGE_SELECTORS:
        try:
            if article.locator(sel).count() > 0:
                return True
        except Exception:
            continue
    return False


def _is_valid_timeline_post(article: Any, base: str, slug: str, *, relaxed: bool = False) -> bool:
    text = _article_inner_text(article)
    if not text or is_sidebar_noise(text) or is_pinned_article_text(text):
        return False
    if is_comment_ui_article(text):
        return False

    permalink = _find_post_permalink(article, base)
    if not permalink or is_comment_href(permalink):
        return False
    if not _permalink_matches_profile(permalink, slug):
        return False

    if not _has_valid_post_timestamp(article, relaxed=relaxed):
        return False

    caption = _extract_message(article)
    if not _has_story_content(article, text, caption):
        if relaxed and len(text) >= 40 and not is_comment_ui_article(text):
            return True
        return False

    return True


def _extract_timestamp(article: Any) -> tuple[str | None, str | None]:
    try:
        loc = article.locator('a[href*="/posts/"] time[datetime], a[href*="pfbid"] time[datetime]')
        for i in range(min(loc.count(), 8)):
            try:
                raw_href = _anchor_href_from_node(loc.nth(i))
                if raw_href and is_comment_href(raw_href):
                    continue
                iso_val = (loc.nth(i).get_attribute("datetime") or "").strip()
                label = (loc.nth(i).inner_text(timeout=1_000) or "").strip()
                if iso_val:
                    return label or iso_val, iso_val
            except Exception:
                continue
    except Exception:
        pass

    try:
        loc = article.locator('a[href*="/posts/"] abbr[title], a[href*="pfbid"] abbr[title]')
        for i in range(min(loc.count(), 8)):
            try:
                raw_href = _anchor_href_from_node(loc.nth(i))
                if raw_href and is_comment_href(raw_href):
                    continue
                title = (loc.nth(i).get_attribute("title") or "").strip()
                if title and re.search(
                    r"\d{4}|\d{1,2}:\d{2}|\d{1,2}h|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec",
                    title,
                    re.I,
                ):
                    return title, None
            except Exception:
                continue
    except Exception:
        pass

    try:
        post_links = article.locator('a[href*="/posts/"], a[href*="pfbid"]')
        for i in range(min(post_links.count(), 12)):
            try:
                link = post_links.nth(i)
                href = link.get_attribute("href") or ""
                if not _is_non_comment_post_href(href):
                    continue
                label = (link.inner_text(timeout=800) or "").strip()
                if looks_like_relative_time(label):
                    return label, None
                aria = (link.get_attribute("aria-label") or "").strip()
                if looks_like_relative_time(aria):
                    return aria, None
            except Exception:
                continue
    except Exception:
        pass
    return None, None


def _extract_message(article: Any) -> str:
    for sel in _MESSAGE_SELECTORS:
        try:
            loc = article.locator(sel)
            if loc.count() == 0:
                continue
            text = (loc.first.inner_text(timeout=2_000) or "").strip()
            if text and len(text) > 3:
                return text
        except Exception:
            continue

    _JS_EXTRACT = """
        el => {
            const SKIP = [
                'see more', 'see less', 'pinned post', 'other posts',
                'rate this translation', 'communities', 'subscriber hub',
                'write a comment', 'write a public comment',
            ];
            const ACTION_LABELS = [
                'like', 'comment', 'share',
                'gusto', "j'aime", 'me gusta', 'curtir',
                'komento', 'ibahagi',
            ];
            let actionY = Infinity;
            const buttons = el.querySelectorAll('[role="button"], button');
            for (const btn of buttons) {
                const lbl = (btn.getAttribute('aria-label') || btn.innerText || '')
                    .toLowerCase().trim();
                if (ACTION_LABELS.some(a => lbl === a || lbl.startsWith(a + ' '))) {
                    const rect = btn.getBoundingClientRect();
                    if (rect.top > 0 && rect.top < actionY) actionY = rect.top;
                }
            }
            const blocks = el.querySelectorAll('[dir="auto"]');
            let best = '';
            for (const block of blocks) {
                const parentArticle = block.closest('[role="article"]');
                if (parentArticle && parentArticle !== el) continue;
                if (actionY !== Infinity) {
                    const rect = block.getBoundingClientRect();
                    if (rect.top >= actionY) continue;
                }
                const text = (block.innerText || '').trim();
                if (!text || text.length < 8) continue;
                const lower = text.toLowerCase();
                if (SKIP.some(s => lower.includes(s))) continue;
                if (text.length > best.length) best = text;
            }
            return best;
        }
    """
    try:
        text = (article.evaluate(_JS_EXTRACT) or "").strip()
        if text and len(text) > 3:
            return text
    except Exception:
        pass
    return ""


def _extract_images(article: Any) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    try:
        imgs = article.locator("img")
        for i in range(min(imgs.count(), 15)):
            src = imgs.nth(i).get_attribute("src") or ""
            srcset = imgs.nth(i).get_attribute("srcset") or ""
            candidates = [src]
            if srcset:
                candidates.extend(p.strip().split()[0] for p in srcset.split(",") if p.strip())
            for url in candidates:
                if url and url not in seen and _looks_like_post_image(url):
                    seen.add(url)
                    urls.append(url)
    except Exception:
        pass
    urls.sort(key=lambda u: ("scontent" in u, len(u)), reverse=True)
    return urls


def _find_post_permalink(article: Any, base: str) -> str | None:
    try:
        links = article.locator("a[href]")
        for i in range(min(links.count(), 30)):
            href = links.nth(i).get_attribute("href") or ""
            clean = resolve_post_permalink(href, base)
            if clean:
                return clean
        html = article.evaluate("el => el.innerHTML || ''") or ""
        return find_permalink_in_fragment(html, base)
    except Exception:
        pass
    return None


def _locate_story_after_other_posts(page: Any) -> Any | None:
    for label in other_posts_labels():
        try:
            marker = page.get_by_text(label, exact=False).first
            for xpath in (
                "following::*[@aria-posinset][1]",
                'following::*[@data-ad-rendering-role="description"][1]/ancestor::*[@aria-posinset][1]',
                'following::*[@data-ad-rendering-role="description"][1]',
            ):
                loc = marker.locator(f"xpath={xpath}")
                if loc.count() > 0:
                    return loc.first
        except Exception:
            continue
    return None


def _build_post_from_article(article: Any, base: str) -> FbTopPost | None:
    permalink = _find_post_permalink(article, base)
    if not permalink:
        return None

    post_id = extract_post_id_from_href(permalink) or safe_post_id(permalink)
    posted_label, posted_iso = _extract_timestamp(article)
    posted_at = posted_iso or posted_label
    text = _extract_message(article)
    if not text:
        text = _article_inner_text(article)
    image_urls = tuple(_extract_images(article))

    return FbTopPost(
        post_id=post_id,
        permalink=permalink,
        text=text,
        image_urls=image_urls,
        posted_at=posted_at,
        posted_at_iso=posted_iso,
    )


def _try_extract_article(
    article: Any,
    base: str,
    slug: str,
    note: str,
    *,
    relaxed: bool,
) -> tuple[FbTopPost | None, str] | None:
    try:
        if not _is_valid_timeline_post(article, base, slug, relaxed=relaxed):
            return None
        post = _build_post_from_article(article, base)
        if post is None:
            return None
        suffix = "_relaxed" if relaxed else ""
        return post, f"{note}{suffix}"
    except Exception:
        return None


def extract_top_post_from_playwright(
    page: Any,
    profile_url: str,
) -> tuple[FbTopPost | None, str]:
    """Return (post, debug_note) — debug_note describes which strategy matched."""
    from parsel import Selector

    base = _base_url(profile_url)
    slug = _profile_slug(profile_url)

    story = _locate_story_after_other_posts(page)
    if story is not None:
        try:
            html = story.evaluate("el => el.outerHTML || ''") or ""
            post = build_post_from_story_root(
                Selector(text=html), profile_url, html_fragment=html
            )
            if post is not None:
                return post, "other_posts_story_block"
        except Exception:
            pass

    direct = _article_after_other_posts_locator(page)
    if direct is not None:
        for relaxed in (False, True):
            hit = _try_extract_article(
                direct, base, slug, "other_posts_following_xpath", relaxed=relaxed
            )
            if hit:
                return hit

    articles = _locate_feed_articles(page)
    try:
        count = articles.count()
    except Exception:
        return None, "no_articles"

    if count == 0:
        return None, "no_articles"

    start = _other_posts_start_index(page, articles, count)
    if start >= 0:
        note = f"other_posts_bbox_index_{start}"
    elif _page_has_pinned_label(page):
        start = feed_start_index(True, skip_pinned=True)
        note = f"pinned_skip_index_{start}_no_other_posts_marker"
    else:
        start = 0
        note = "feed_index_0_no_markers"

    for relaxed in (False, True):
        for i in range(start, min(count, 15)):
            try:
                article = articles.nth(i)
            except Exception:
                continue
            hit = _try_extract_article(
                article, base, slug, f"{note}@article_{i}", relaxed=relaxed
            )
            if hit:
                return hit

    if start >= 0:
        return None, f"{note}_validation_failed"
    return None, note


def _scroll_page_down(page: Any) -> None:
    try:
        page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.9))")
        page.wait_for_timeout(2000)
    except Exception:
        pass


def _collect_stories_from_html(
    page: Any,
    profile_url: str,
    seen_ids: set[str],
    *,
    max_posts: int,
) -> list[FbTopPost]:
    from parsel import Selector

    from src.scraper.parsers.fb_story_blocks import parse_stories_after_other_posts

    try:
        html = page.content()
    except Exception:
        return []

    found: list[FbTopPost] = []
    for post in parse_stories_after_other_posts(
        Selector(text=html), profile_url, max_posts=max_posts * 3
    ):
        if post.post_id in seen_ids:
            continue
        seen_ids.add(post.post_id)
        found.append(post)
    return found


def _collect_stories_from_locators(
    page: Any,
    profile_url: str,
    seen_ids: set[str],
) -> list[FbTopPost]:
    from parsel import Selector

    found: list[FbTopPost] = []
    xpaths = (
        "following::*[@aria-posinset]",
        'following::*[@data-ad-rendering-role="description"]/ancestor::*[@aria-posinset][1]',
        'following::*[@data-ad-rendering-role="description"]',
    )
    for label in other_posts_labels():
        try:
            marker = page.get_by_text(label, exact=False).first
        except Exception:
            continue
        for xpath in xpaths:
            try:
                loc = marker.locator(f"xpath={xpath}")
                count = loc.count()
            except Exception:
                continue
            for i in range(min(count, 40)):
                try:
                    node = loc.nth(i)
                    html = node.evaluate("el => el.outerHTML || ''") or ""
                    post = build_post_from_story_root(
                        Selector(text=html), profile_url, html_fragment=html
                    )
                    if post is None or post.post_id in seen_ids:
                        continue
                    seen_ids.add(post.post_id)
                    found.append(post)
                except Exception:
                    continue
    return found


def extract_daily_posts_from_playwright(
    page: Any,
    profile_url: str,
    *,
    max_posts: int,
    scroll_passes: int,
) -> tuple[list[FbTopPost], str]:
    """Scroll the profile feed repeatedly; virtualized DOM only exposes a few posts at a time."""
    seen_ids: set[str] = set()
    ordered: list[FbTopPost] = []

    def _merge(batch: list[FbTopPost]) -> int:
        added = 0
        for post in batch:
            if post.post_id in seen_ids:
                continue
            seen_ids.add(post.post_id)
            ordered.append(post)
            added += 1
        return added

    _scroll_other_posts_marker(page)
    _merge(_collect_stories_from_locators(page, profile_url, seen_ids))
    _merge(_collect_stories_from_html(page, profile_url, seen_ids, max_posts=max_posts))

    stagnant_rounds = 0
    for _ in range(max(scroll_passes, 1)):
        if len(ordered) >= max_posts:
            break
        before = len(ordered)
        _scroll_page_down(page)
        _scroll_other_posts_marker(page)
        _merge(_collect_stories_from_locators(page, profile_url, seen_ids))
        _merge(_collect_stories_from_html(page, profile_url, seen_ids, max_posts=max_posts))
        if len(ordered) == before:
            stagnant_rounds += 1
            if stagnant_rounds >= 2:
                break
        else:
            stagnant_rounds = 0

    if ordered:
        return ordered[:max_posts], f"daily_collected_{len(ordered)}_scroll_{scroll_passes}"
    return [], "daily_no_posts"
