"""Map Facebook post time labels to dates / hours-ago (daily scrape window)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.models.fb_model import FbTopPost

_MANILA_OFFSET = timezone(timedelta(hours=8))
_DEFAULT_DAILY_MAX_HOURS = 23

_MONTH_DAY = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b",
    re.I,
)
# Facebook UI: "1h", "2h", "23h" (= hours ago); also "5m", "1 d"
_HOURS_AGO_TOKEN = re.compile(r"\b(\d+)\s*h(?:ours?|rs?)?\b", re.I)
_MINUTES_AGO_TOKEN = re.compile(r"\b(\d+)\s*m(?:ins?|inutes?)?\b", re.I)
_DAYS_AGO_TOKEN = re.compile(r"\b(\d+)\s*d(?:ays?)?\b", re.I)
_COMPACT_HM = re.compile(r"^(\d+)([hdm])$", re.I)


def _zoneinfo(tz_name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except Exception:
        if tz_name in ("Asia/Manila", "Asia/Singapore", "Asia/Kuala_Lumpur"):
            return _MANILA_OFFSET
        return timezone.utc


def today_in_timezone(tz_name: str) -> date:
    return datetime.now(_zoneinfo(tz_name)).date()


def now_in_timezone(tz_name: str) -> datetime:
    return datetime.now(_zoneinfo(tz_name))


def parse_hours_ago(label: str) -> float | None:
    """Parse FB relative time. Examples: 1h → 1.0, 23h → 23.0, 5m → ~0.08."""
    raw = (label or "").strip()
    if not raw:
        return None

    lower = raw.lower()
    if "just now" in lower:
        return 0.0
    if "yesterday" in lower:
        return 36.0

    compact = _COMPACT_HM.match(lower)
    if compact:
        amount, unit = int(compact.group(1)), compact.group(2).lower()
        if unit == "h":
            return float(amount)
        if unit == "m":
            return amount / 60.0
        if unit == "d":
            return amount * 24.0

    match = _HOURS_AGO_TOKEN.search(lower)
    if match:
        return float(match.group(1))

    match = _MINUTES_AGO_TOKEN.search(lower)
    if match:
        return int(match.group(1)) / 60.0

    match = _DAYS_AGO_TOKEN.search(lower)
    if match:
        return int(match.group(1)) * 24.0

    return None


def post_hours_ago(post: FbTopPost, tz_name: str) -> float | None:
    if post.posted_at_iso:
        try:
            raw = post.posted_at_iso.replace("Z", "+00:00")
            posted = datetime.fromisoformat(raw)
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=_zoneinfo(tz_name))
            age = now_in_timezone(tz_name) - posted.astimezone(_zoneinfo(tz_name))
            return max(age.total_seconds() / 3600.0, 0.0)
        except ValueError:
            pass

    if post.posted_at:
        return parse_hours_ago(post.posted_at)
    return None


def post_in_daily_window(
    post: FbTopPost,
    tz_name: str,
    *,
    max_hours: int = _DEFAULT_DAILY_MAX_HOURS,
) -> bool:
    """True if post is within the last max_hours (default 23h: 1h…23h, minutes, just now)."""
    hours = post_hours_ago(post, tz_name)
    if hours is not None:
        return hours <= max_hours

    # Absolute date fallback (e.g. May 18) when no 1h-style label
    parsed = post_calendar_date(post, tz_name)
    if parsed is not None:
        return parsed == today_in_timezone(tz_name)

    return True


def post_too_old_for_daily_feed(
    post: FbTopPost,
    tz_name: str,
    *,
    max_hours: int = _DEFAULT_DAILY_MAX_HOURS,
) -> bool:
    """Stop scrolling when post is older than the daily window."""
    hours = post_hours_ago(post, tz_name)
    if hours is not None:
        return hours > max_hours

    parsed = post_calendar_date(post, tz_name)
    if parsed is not None:
        return parsed < today_in_timezone(tz_name)

    return False


def _parse_month_day(label: str, reference: date) -> date | None:
    match = _MONTH_DAY.search(label)
    if not match:
        return None
    month_str, day_str = match.group(1), match.group(2)
    for fmt in ("%b %d %Y", "%B %d %Y"):
        try:
            return datetime.strptime(f"{month_str} {day_str} {reference.year}", fmt).date()
        except ValueError:
            continue
    return None


def post_calendar_date(post: FbTopPost, tz_name: str) -> date | None:
    if post.posted_at_iso:
        try:
            raw = post.posted_at_iso.replace("Z", "+00:00")
            return datetime.fromisoformat(raw).astimezone(_zoneinfo(tz_name)).date()
        except ValueError:
            pass

    label = (post.posted_at or "").strip()
    if not label:
        return None

    lower = label.lower()
    today = today_in_timezone(tz_name)

    if parse_hours_ago(label) is not None:
        return today
    if "yesterday" in lower:
        return today - timedelta(days=1)

    month_day = _parse_month_day(label, today)
    if month_day is not None:
        return month_day

    if re.search(r"\d{4}", label):
        for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(label[:30], fmt).date()
            except ValueError:
                continue
    return None


def post_on_target_day(post: FbTopPost, target: date, tz_name: str) -> bool:
    parsed = post_calendar_date(post, tz_name)
    if parsed is not None:
        return parsed == target
    return True


def post_is_older_than_target(post: FbTopPost, target: date, tz_name: str) -> bool:
    parsed = post_calendar_date(post, tz_name)
    if parsed is not None:
        return parsed < target
    return False
