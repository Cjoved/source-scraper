"""Typed shapes for scraped corpus rows."""

from dataclasses import dataclass


@dataclass(frozen=True)
class YieldRecord:
    symbol: str
    yield_pct: float
