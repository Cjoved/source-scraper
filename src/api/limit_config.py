"""Dynamic rate-limit strings from settings (for slowapi decorators)."""

from __future__ import annotations

from src.api.settings import get_settings


def rate_limit_read() -> str:
    return get_settings().rate_limit_read


def rate_limit_search() -> str:
    return get_settings().rate_limit_search


def rate_limit_export() -> str:
    return get_settings().rate_limit_export


def rate_limit_health() -> str:
    return get_settings().rate_limit_health


def rate_limit_agent() -> str:
    return get_settings().rate_limit_agent
