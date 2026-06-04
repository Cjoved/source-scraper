"""Temporary environment overrides for a single orchestrator job run."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def job_env(overrides: dict[str, str]) -> Iterator[None]:
    """Apply env overrides for the duration of the context, then restore."""
    if not overrides:
        yield
        return

    backup: dict[str, str | None] = {k: os.environ.get(k) for k in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, previous in backup.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
