"""Cron schedule matching for orchestrator --due runs."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from croniter import croniter


def job_due_now(
    cron_expr: str,
    tz_name: str,
    now: datetime | None = None,
    *,
    tolerance_minutes: int = 1,
) -> bool:
    """
    Return True if ``cron_expr`` matches ``now`` in ``tz_name``.

    Uses a tolerance window so a cron entry polled once per minute
    does not miss the exact tick.
    """
    zone = ZoneInfo(tz_name)
    current = (now or datetime.now(tz=zone)).astimezone(zone)
    for offset in range(tolerance_minutes + 1):
        check = current - timedelta(minutes=offset)
        if croniter.match(cron_expr, check):
            return True
    return False


def next_run_time(cron_expr: str, tz_name: str, now: datetime | None = None) -> datetime:
    """Return the next scheduled run after ``now`` in the given timezone."""
    zone = ZoneInfo(tz_name)
    base = (now or datetime.now(tz=zone)).astimezone(zone)
    itr = croniter(cron_expr, base)
    nxt = itr.get_next(datetime)
    if nxt.tzinfo is None:
        return nxt.replace(tzinfo=zone)
    return nxt.astimezone(zone)
