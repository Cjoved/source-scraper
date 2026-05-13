"""Manual eval runner for the knowledge search endpoint.

This is **not** a hard-pass test. It runs a small natural-language query set
against a live API and reports per-query summaries so we can compare changes
to textification / embeddings / fusion over time.

Usage::

    uv run python -m tests.eval.run_eval \
        --base-url http://localhost:8000 \
        --api-key <public-key>

If the API requires no auth (``API_AUTH_DISABLED=true``), ``--api-key`` is optional.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

DEFAULT_QUERIES = Path(__file__).with_name("yield_queries.jsonl")


def _load_queries(path: Path) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            queries.append(json.loads(line))
    return queries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run knowledge search eval set.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args(argv)

    queries = _load_queries(args.queries)
    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    failures = 0
    print(f"Running {len(queries)} eval queries against {args.base_url}")

    for idx, item in enumerate(queries, start=1):
        body = {"query": item["query"], "limit": args.limit}
        url = f"{args.base_url.rstrip('/')}/v1/knowledge/search"
        try:
            response = requests.post(url, headers=headers, json=body, timeout=30)
        except requests.RequestException as exc:
            failures += 1
            print(f"[{idx:02d}] {item['query']!r} -> REQUEST FAILED: {exc}")
            continue

        if response.status_code != 200:
            failures += 1
            print(f"[{idx:02d}] {item['query']!r} -> HTTP {response.status_code}: {response.text}")
            continue

        payload = response.json()
        hits = payload.get("hits", [])
        if not hits:
            print(f"[{idx:02d}] {item['query']!r} -> no hits")
            continue

        top = hits[0]
        print(
            f"[{idx:02d}] {item['query']!r} -> "
            f"top: {top['municipality']} {top['province']} {top['region']} "
            f"{top['year']} sem={top['semester_code']} score={top['score']:.3f}"
        )

    if failures:
        print(f"\n{failures} queries failed to reach the API.")
        return 1
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
