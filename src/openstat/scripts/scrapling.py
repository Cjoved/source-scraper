"""
Scrapling fetcher/browser setup mula sa code (kapag hindi gumagana ang `scrapling` sa PATH).

Usage (mula sa project root):
  python -m src.scripts.scrapling
  python -m src.scripts.scrapling --force
"""
from __future__ import annotations

import argparse

from scrapling.cli import install as scrapling_install  # type: ignore[import-unresolved]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run scrapling install (browser deps).")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reinstall fetcher/browser dependencies.",
    )
    args = parser.parse_args()
    argv: list[str] = ["--force"] if args.force else []
    scrapling_install(argv, standalone_mode=False)


if __name__ == "__main__":
    main()
