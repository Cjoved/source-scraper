"""Apply playwright-stealth to a Playwright page (v1 stealth_sync or v2 Stealth API)."""

from __future__ import annotations

from typing import Any


def apply_page_stealth(page: Any) -> bool:
    """
    Apply stealth evasions to a sync Playwright page or context.
    Returns True if applied, False if package missing or application failed.
    """
    try:
        from playwright_stealth import stealth_sync

        stealth_sync(page)
        return True
    except ImportError:
        pass
    except Exception:
        pass

    try:
        from playwright_stealth import Stealth

        Stealth().apply_stealth_sync(page)
        return True
    except ImportError:
        return False
    except Exception:
        return False


def stealth_available() -> bool:
    try:
        import playwright_stealth  # noqa: F401

        return True
    except ImportError:
        return False
