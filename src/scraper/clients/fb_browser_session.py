"""Facebook login, navigation, and logout via Scrapling StealthySession."""

from __future__ import annotations

import random
import re
import time
from typing import Any, Callable

from rich.console import Console

from src.models.fb_model import FbPageConfig, FbTopPost
from src.scraper.parsers.fb_feed_helpers import other_posts_labels
from src.scraper.parsers.fb_playwright_extract import (
    extract_daily_posts_from_playwright,
    extract_top_post_from_playwright,
)

FB_LOGIN_URL = "https://www.facebook.com/login"
FB_LOGOUT_URL = "https://www.facebook.com/logout.php"


def profile_posts_url(profile_url: str) -> str:
    base = profile_url.rstrip("/")
    if base.endswith("/posts"):
        return base
    return f"{base}/posts"


def profile_scrape_url(profile_url: str, *, use_all_tab: bool) -> str:
    base = profile_url.rstrip("/")
    if use_all_tab:
        if base.endswith("/posts"):
            return base[: -len("/posts")]
        return base
    return profile_posts_url(profile_url)


def is_logged_in(session: Any) -> bool:
    context = getattr(session, "context", None)
    if context is None:
        return False
    try:
        for cookie in context.cookies():
            if cookie.get("name") == "c_user" and cookie.get("value"):
                return True
    except Exception:
        return False
    return False


def _pause_seconds(cfg: FbPageConfig) -> float:
    lo = min(cfg.login_delay_min, cfg.login_delay_max)
    hi = max(cfg.login_delay_min, cfg.login_delay_max)
    return random.uniform(lo, hi)


def _human_pause(page: Any, cfg: FbPageConfig) -> None:
    page.wait_for_timeout(int(_pause_seconds(cfg) * 1000))


def _human_type(page: Any, locator: Any, text: str, cfg: FbPageConfig) -> None:
    field = locator.first
    field.click(timeout=20_000)
    _human_pause(page, cfg)
    try:
        field.press_sequentially(text, delay=cfg.login_typing_delay_ms)
    except Exception:
        field.fill(text, timeout=20_000)


def _fill_login_form(page: Any, cfg: FbPageConfig, email: str, password: str) -> None:
    page.wait_for_timeout(int(cfg.login_page_wait * 1000))

    email_selectors = (
        "input#email",
        'input[name="email"]',
        'input[type="email"]',
        'input[autocomplete="username"]',
    )
    pass_selectors = (
        "input#pass",
        'input[name="pass"]',
        'input[type="password"]',
        'input[autocomplete="current-password"]',
    )

    filled_email = False
    for sel in email_selectors:
        loc = page.locator(sel)
        if loc.count() > 0:
            _human_type(page, loc, email, cfg)
            filled_email = True
            break
    if not filled_email:
        raise RuntimeError("Facebook login email field not found")

    _human_pause(page, cfg)

    filled_pass = False
    for sel in pass_selectors:
        loc = page.locator(sel)
        if loc.count() > 0:
            _human_type(page, loc, password, cfg)
            filled_pass = True
            break
    if not filled_pass:
        raise RuntimeError("Facebook login password field not found")

    _human_pause(page, cfg)

    submitted = _click_login_submit(page)
    if not submitted:
        page.keyboard.press("Enter")

    page.wait_for_timeout(int(cfg.login_after_submit_wait * 1000))


def _click_login_submit(page: Any) -> bool:
    submit_selectors = (
        'button[name="login"]',
        'button[type="submit"]',
        'button[data-testid="royal-login-button"]',
        'form button[type="submit"]',
    )
    for sel in submit_selectors:
        loc = page.locator(sel)
        if loc.count() > 0:
            loc.first.click(timeout=15_000)
            return True

    for label in ("Log in", "Log In", "Login"):
        try:
            btn = page.get_by_role("button", name=label, exact=True)
            if btn.count() > 0:
                btn.first.click(timeout=15_000)
                return True
        except Exception:
            pass

    try:
        loc = page.locator('motion.div[role="button"]:has-text("Log in")')
        if loc.count() > 0:
            loc.first.click(timeout=15_000)
            return True
    except Exception:
        pass

    try:
        loc = page.locator('motion.div[role="button"]:has-text("Log In")')
        if loc.count() > 0:
            loc.first.click(timeout=15_000)
            return True
    except Exception:
        pass

    return False


def _wait_logged_in(page: Any, timeout_ms: int = 90_000) -> None:
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        url = (page.url or "").lower()
        if page.locator('input[name="pass"], input#pass').count() > 0 and "login" in url:
            time.sleep(1.0)
            continue
        if page.locator('[data-pagelet="FeedUnit"], div[role="feed"]').count() > 0:
            return
        if page.locator('[aria-label="Your profile"], [aria-label="Account"]').count() > 0:
            return
        if "login" not in url and "checkpoint" not in url and "two_step" not in url:
            return
        time.sleep(1.0)
    raise RuntimeError("Facebook login did not complete (still on login/checkpoint)")


def make_login_page_action(cfg: FbPageConfig) -> Callable[[Any], None]:
    def _action(page: Any) -> None:
        if not cfg.email or not cfg.password:
            raise RuntimeError("FB_EMAIL and FB_PASSWORD are required for auto-login")
        _fill_login_form(page, cfg, cfg.email, cfg.password)
        _wait_logged_in(page)
        _human_pause(page, cfg)

    return _action


def _scroll_other_posts_section(page: Any) -> bool:
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


def make_profile_page_action(
    cfg: FbPageConfig,
    extract_holder: list[FbTopPost] | None = None,
    extract_note_holder: list[str] | None = None,
) -> Callable[[Any], None]:
    def _action(page: Any) -> None:
        if cfg.js_settle_seconds > 0:
            page.wait_for_timeout(int(cfg.js_settle_seconds * 1000))

        if cfg.profile_use_all_tab:
            for label in ("All", "Lahat"):
                try:
                    tab = page.get_by_role("tab", name=re.compile(f"^{label}$", re.I))
                    if tab.count() > 0:
                        tab.first.click(timeout=10_000)
                        page.wait_for_timeout(2000)
                        break
                except Exception:
                    pass
        else:
            for label in ("Posts", "Publication"):
                try:
                    tab = page.get_by_role("tab", name=re.compile(label, re.I))
                    if tab.count() > 0:
                        tab.first.click(timeout=10_000)
                        page.wait_for_timeout(3000)
                        break
                except Exception:
                    pass

        try:
            posts_heading = page.get_by_role("heading", name=re.compile(r"^Posts$", re.I))
            if posts_heading.count() > 0:
                posts_heading.first.scroll_into_view_if_needed(timeout=10_000)
                page.wait_for_timeout(1500)
        except Exception:
            pass

        _scroll_other_posts_section(page)

        try:
            page.locator('[role="main"] [role="article"], [role="article"]').first.wait_for(
                state="attached",
                timeout=15_000,
            )
        except Exception:
            pass

        if extract_holder is not None:
            extract_holder.clear()
            if cfg.scrape_mode == "daily":
                posts, note = extract_daily_posts_from_playwright(
                    page,
                    cfg.profile_url,
                    max_posts=cfg.max_posts_per_run,
                    scroll_passes=cfg.daily_scroll_passes,
                )
                extract_holder.extend(posts)
            else:
                post, note = extract_top_post_from_playwright(page, cfg.profile_url)
                if post is not None:
                    extract_holder.append(post)
            if extract_note_holder is not None:
                extract_note_holder.clear()
                extract_note_holder.append(note)

    return _action


def fetch_with_session(
    session: Any,
    url: str,
    *,
    page_action: Callable[[Any], None] | None = None,
    google_search: bool = False,
    network_idle: bool = True,
    load_dom: bool = True,
    disable_resources: bool = False,
) -> Any:
    kwargs: dict[str, Any] = {
        "google_search": google_search,
        "network_idle": network_idle,
        "load_dom": load_dom,
        "disable_resources": disable_resources,
    }
    if page_action is not None:
        kwargs["page_action"] = page_action
    try:
        return session.fetch(url, **kwargs)
    except TypeError:
        return session.fetch(url)


def fb_login(session: Any, cfg: FbPageConfig, console: Console) -> None:
    console.print(
        "[dim]Logging in to Facebook "
        f"(human delays {cfg.login_delay_min}–{cfg.login_delay_max}s, "
        f"typing {cfg.login_typing_delay_ms}ms/char)…[/dim]"
    )
    login_error: list[str] = []

    def _action(page: Any) -> None:
        try:
            make_login_page_action(cfg)(page)
        except Exception as e:
            login_error.append(str(e))
            raise

    fetch_with_session(
        session,
        FB_LOGIN_URL,
        page_action=_action,
        disable_resources=False,
        google_search=False,
    )

    if login_error:
        raise RuntimeError(login_error[0])
    if not is_logged_in(session):
        raise RuntimeError(
            "Facebook login failed (no session cookie). "
            "Try FB_HEADLESS=false or check FB_EMAIL/FB_PASSWORD."
        )
    console.print("[green]Login OK[/green]")


def fb_fetch_profile(
    session: Any,
    cfg: FbPageConfig,
    console: Console,
    extract_holder: list[FbTopPost] | None = None,
    extract_note_holder: list[str] | None = None,
) -> Any:
    target_url = profile_scrape_url(cfg.profile_url, use_all_tab=cfg.profile_use_all_tab)
    tab_label = "All tab" if cfg.profile_use_all_tab else "Posts tab"
    console.print(f"[bold]→[/bold] {target_url} [dim]({tab_label})[/dim]")
    return fetch_with_session(
        session,
        target_url,
        page_action=make_profile_page_action(cfg, extract_holder, extract_note_holder),
        disable_resources=False,
        google_search=False,
    )


def fb_logout(session: Any, cfg: FbPageConfig, console: Console) -> None:
    if not cfg.logout_after:
        return
    console.print("[dim]Logging out (clearing session)…[/dim]")
    context = getattr(session, "context", None)
    if context is not None:
        try:
            fetch_with_session(session, FB_LOGOUT_URL, network_idle=False, load_dom=False)
        except Exception:
            pass
        try:
            context.clear_cookies()
        except Exception:
            pass
    console.print("[green]Session cleared[/green]")


def open_stealth_session(cfg: FbPageConfig) -> Any:
    from scrapling.fetchers import StealthySession

    return StealthySession(
        headless=cfg.headless,
        solve_cloudflare=False,
        disable_resources=False,
        google_search=False,
    )
