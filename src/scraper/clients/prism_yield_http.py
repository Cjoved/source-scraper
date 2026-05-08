"""HTTP client for PRiSM wp-dynamicreports/map — polite retries."""

from __future__ import annotations

import random
import time
from typing import Any, Protocol

import requests
from rich.console import Console

from src.scraper.prism_constants import BASE_SITE, PRISM_MAP_BASE, REFERER_PAGE


class YieldMapPoster(Protocol):
    def post(self, path: str, data: dict[str, Any]) -> str | None: ...

    def polite_sleep(self) -> None: ...


class PrismYieldHttpClient:
    def __init__(
        self,
        *,
        delay: float = 1.0,
        jitter: float = 0.55,
        retries: int = 5,
        timeout: int = 90,
        console: Console | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._delay = delay
        self._jitter = jitter
        self._retries = retries
        self._timeout = timeout
        self._console = console or Console()
        self._session = session or self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-PH,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Origin": BASE_SITE,
                "Referer": REFERER_PAGE,
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
        )
        return s

    def polite_sleep(self) -> None:
        extra = random.uniform(0, self._jitter) if self._jitter > 0 else 0.0
        time.sleep(self._delay + extra)

    def post(self, path: str, data: dict[str, Any], *, timeout: int | None = None) -> str | None:
        url = f"{PRISM_MAP_BASE}/{path.lstrip('/')}"
        to = timeout if timeout is not None else self._timeout
        for attempt in range(self._retries):
            try:
                r = self._session.post(url, data=data, timeout=to)
                if r.status_code == 429:
                    wait = int(r.headers.get("Retry-After", "20"))
                    wait = max(5, min(wait, 120))
                    self._console.print(
                        f"[yellow]429 Too Many Requests — waiting {wait}s "
                        f"(attempt {attempt + 1}/{self._retries})[/yellow]"
                    )
                    time.sleep(wait)
                    continue
                if r.status_code in (502, 503, 504):
                    backoff = min(45.0, 3.0 * (2**attempt))
                    self._console.print(
                        f"[yellow]HTTP {r.status_code} — backoff {backoff:.0f}s "
                        f"(attempt {attempt + 1}/{self._retries})[/yellow]"
                    )
                    time.sleep(backoff)
                    continue
                r.raise_for_status()
                return r.text
            except requests.RequestException as e:
                if attempt + 1 >= self._retries:
                    self._console.print(f"[red]POST failed {url}: {e}[/red]")
                    return None
                time.sleep(min(30.0, 2.0 * (attempt + 1)))
        return None
