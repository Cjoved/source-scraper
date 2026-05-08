from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def retry(times: int = 3, backoff_seconds: float = 0.5) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Tiny retry helper for flaky HTTP; expand with logging/backoff as needed."""

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exc: BaseException | None = None
            for attempt in range(times):
                try:
                    return fn(*args, **kwargs)
                except BaseException as exc:  # noqa: BLE001 — scaffold; tighten per call-site
                    last_exc = exc
                    if attempt == times - 1:
                        raise
                    time.sleep(backoff_seconds * (attempt + 1))
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator
