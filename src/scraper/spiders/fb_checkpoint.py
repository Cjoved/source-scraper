"""Checkpoint helpers for Facebook profile scrape."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


def should_persist_post(last_post_id: str | None, new_post_id: str) -> bool:
    if not last_post_id:
        return True
    return last_post_id != new_post_id


def should_persist_post_id(seen_post_ids: set[str], post_id: str) -> bool:
    return post_id not in seen_post_ids


def load_seen_post_ids(checkpoint: dict[str, Any], jsonl_path: Path | None = None) -> set[str]:
    seen: set[str] = set()
    raw = checkpoint.get("seen_post_ids")
    if isinstance(raw, list):
        seen.update(str(x) for x in raw if x)

    last = checkpoint.get("last_post_id")
    if last:
        seen.add(str(last))

    if jsonl_path and jsonl_path.is_file():
        with jsonl_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pid = row.get("post_id")
                if pid:
                    seen.add(str(pid))
    return seen


def build_checkpoint_update(
    profile_url: str,
    post_id: str,
    posted_at: str | None,
    checked_at: str,
    *,
    posted_at_iso: str | None = None,
    seen_post_ids: set[str] | None = None,
    scrape_date: date | None = None,
) -> dict[str, Any]:
    update: dict[str, Any] = {
        "profile_url": profile_url,
        "last_post_id": post_id,
        "last_post_time": posted_at,
        "last_post_time_iso": posted_at_iso,
        "last_checked_at": checked_at,
    }
    if seen_post_ids is not None:
        update["seen_post_ids"] = sorted(seen_post_ids)
    if scrape_date is not None:
        update["last_scrape_date"] = scrape_date.isoformat()
    return update


def merge_seen_ids(seen: set[str], new_ids: list[str], *, max_size: int = 500) -> set[str]:
    merged = set(seen)
    merged.update(new_ids)
    if len(merged) <= max_size:
        return merged
    return set(sorted(merged)[-max_size:])
