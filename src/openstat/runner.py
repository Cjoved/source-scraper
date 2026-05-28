"""Entrypoint wrapper for OpenStatv2 parity workflows."""

from __future__ import annotations

from src.openstat.main import main as openstat_main


def run() -> int:
    openstat_main()
    return 0

