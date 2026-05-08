"""Extract visible text from Scrapling page objects."""

from __future__ import annotations

import re
from typing import Any

from src.scraper.prism_browser_config import PrismBrowserConfig
from src.scraper.prism_urls import is_prism_dynamic_app


def page_plain_text(page: Any) -> str:
    try:
        chunks = page.xpath("//body//text()[not(ancestor::script) and not(ancestor::style)]").getall()
    except Exception:
        chunks = page.css("body *::text").getall()
    return "\n".join(c.strip() for c in chunks if c and str(c).strip())


def page_title(page: Any) -> str:
    t = page.css("title::text").get()
    if t and t.strip():
        return t.strip()
    h1 = page.css("h1::text").get()
    return (h1 or "").strip()


def _css_with_adaptive(page: Any, selector: str, cfg: PrismBrowserConfig) -> Any:
    kw: dict[str, Any] = {}
    if cfg.adaptive:
        kw["adaptive"] = True
    if cfg.auto_save:
        kw["auto_save"] = True
    return page.css(selector, **kw) if kw else page.css(selector)


def text_from_selector(page: Any, selector: str, cfg: PrismBrowserConfig) -> str:
    blocks = _css_with_adaptive(page, selector, cfg)
    lines: list[str] = []
    try:
        for el in blocks:
            try:
                for chunk in el.xpath(".//text()[not(ancestor::script) and not(ancestor::style)]").getall():
                    s = (chunk or "").strip()
                    if s:
                        lines.append(s)
            except Exception:
                continue
    except TypeError:
        try:
            lines = [
                c.strip()
                for c in blocks.xpath(".//text()[not(ancestor::script) and not(ancestor::style)]").getall()
                if (c or "").strip()
            ]
        except Exception:
            lines = []
    return "\n".join(lines)


def content_selectors_for_url(norm_url: str, cfg: PrismBrowserConfig) -> list[str]:
    if cfg.content_selector:
        return [s.strip() for s in cfg.content_selector.split(",") if s.strip()]
    if is_prism_dynamic_app(norm_url):
        return ["#detail_info", "#content-body"]
    return []


def extract_body_text(page: Any, norm_url: str, cfg: PrismBrowserConfig) -> str:
    for sel in content_selectors_for_url(norm_url, cfg):
        focused = text_from_selector(page, sel, cfg).strip()
        if len(focused) >= cfg.min_content_len:
            return focused
    return page_plain_text(page)


def collapse_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def safe_txt_name(url: str) -> str:
    safe = re.sub(r"[^\w\-.]", "_", url) or "prism_page"
    base = safe[:180] if len(safe) > 180 else safe
    return base if base.lower().endswith(".txt") else f"{base}.txt"
