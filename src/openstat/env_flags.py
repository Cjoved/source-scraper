"""OpenStat workflow enable flags from environment variables."""

import os


def env_enabled(name: str, default: str = "false") -> bool:
    v = (os.getenv(name) or default).strip().lower()
    return v in ("true", "1", "yes")


def philrice_enabled() -> bool:
    return env_enabled("PHILRICE", "false")


def philrice_news_enabled() -> bool:
    return env_enabled("PHILRICE_NEWS", "false")


def pinoyrice_enabled() -> bool:
    return env_enabled("PINOYRICE", "false")


def openstat_enabled() -> bool:
    return env_enabled("OPENSTAT", "true")


def irri_enabled() -> bool:
    return env_enabled("IRRI", "false")


def prism_enabled() -> bool:
    return env_enabled("PRISM", "false")
