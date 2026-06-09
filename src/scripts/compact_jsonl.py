"""
Rewrite a JSONL file so each record is one physical line.

Usage:
    uv run python -m src.scripts.compact_jsonl --path data/philrice_processed/philrice_corpus.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.utils.jsonl import rewrite_jsonl_compact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compact split/wrapped JSONL records to one line each.")
    parser.add_argument("--path", type=Path, required=True, help="JSONL file to rewrite in place")
    parser.add_argument(
        "--no-sanitize",
        action="store_true",
        help="Skip Unicode line-break cleanup in text/input/content",
    )
    args = parser.parse_args(argv)

    path = args.path.resolve()
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    count = rewrite_jsonl_compact(path, sanitize=not args.no_sanitize)
    print(f"Compacted {count} records → {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
