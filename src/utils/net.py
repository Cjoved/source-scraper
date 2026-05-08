"""Lightweight connectivity checks (no Playwright)."""

from __future__ import annotations

import functools
import socket
import time
from typing import Any, Callable, TypeVar

import requests

F = TypeVar("F", bound=Callable[..., Any])


def is_internet_available(*, retries: int = 3, initial_timeout: float = 3.0, max_timeout: float = 15.0) -> bool:
    hosts = ("8.8.8.8", "1.1.1.1")
    port = 53
    timeout = initial_timeout
    for _attempt in range(retries):
        for host in hosts:
            try:
                socket.setdefaulttimeout(timeout)
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.connect((host, port))
                return True
            except OSError:
                continue
        try:
            r = requests.get("https://www.google.com", timeout=timeout)
            if r.status_code == 200:
                return True
        except (requests.ConnectionError, requests.Timeout):
            pass
        timeout = min(timeout * 2, max_timeout)
        time.sleep(2)
    return False


def wait_for_internet(retry_interval: float = 5.0) -> None:
    while not is_internet_available():
        print(f"Internet lost! Retrying in {retry_interval} seconds...")
        time.sleep(retry_interval)


def require_internet(func: F) -> F:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        wait_for_internet()
        return func(*args, **kwargs)

    return wrapper  # type: ignore[return-value]
