"""Browser job lock — at most one browser-heavy orchestrator job at a time."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.services.config import data_path

LOCK_PATH = data_path("checkpoints", "orchestrator_browser.lock")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        process_query_limited = 0x1000
        handle = kernel32.OpenProcess(process_query_limited, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True


def _read_lock() -> dict[str, Any] | None:
    if not LOCK_PATH.is_file():
        return None
    try:
        data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write_lock(job_id: str) -> None:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "job_id": job_id,
        "started_at": datetime.now(UTC).isoformat(),
    }
    tmp = LOCK_PATH.with_suffix(".lock.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, LOCK_PATH)


def _remove_lock() -> None:
    try:
        LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def _release_if_owner() -> None:
    holder = _read_lock()
    if holder and holder.get("pid") == os.getpid():
        _remove_lock()


def lock_holder() -> dict[str, Any] | None:
    """Return current lock holder if alive, else None (clears stale lock)."""
    holder = _read_lock()
    if holder is None:
        return None
    pid = int(holder.get("pid") or 0)
    if _pid_alive(pid):
        return holder
    _remove_lock()
    return None


@contextmanager
def browser_job_lock(job_id: str):
    """
    Acquire browser lock for job_id.

    Yields True if this job holds the lock and should run.
    Yields False if another browser job is active (caller should skip).
    """
    holder = lock_holder()
    if holder is not None:
        yield False
        return

    _write_lock(job_id)
    try:
        yield True
    finally:
        _release_if_owner()


def lock_path_for_tests() -> Path:
    """Expose lock path for tests."""
    return LOCK_PATH
