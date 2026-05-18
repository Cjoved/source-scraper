"""Checkpoint helpers for Facebook profile scrape."""

from __future__ import annotations

from typing import Any


def should_persist_post(last_post_id: str | None, new_post_id: str) -> bool:
    if not last_post_id:
        return True
    return last_post_id != new_post_id


def build_checkpoint_update(
    profile_url: str,
    post_id: str,
    posted_at: str | None,
    checked_at: str,
    *,
    posted_at_iso: str | None = None,
) -> dict[str, Any]:
    return {
        "profile_url": profile_url,
        "last_post_id": post_id,
        "last_post_time": posted_at,
        "last_post_time_iso": posted_at_iso,
        "last_checked_at": checked_at,
    }
