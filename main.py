"""Single entry point for scraper, API server, and indexer.

Usage:

    uv run python main.py                # default: scrape (back-compat)
    uv run python main.py scrape         # explicit scrape mode
    uv run python main.py openstat       # run OpenStatv2 parity workflows
    uv run python main.py api            # start FastAPI via uvicorn
    uv run python main.py index --all    # run the PRiSM yield Qdrant indexer
    uv run python main.py index-prices   # run the OpenSTAT price Qdrant indexer
    uv run uvicorn main:app              # uvicorn directly (uses re-exported `app`)

The FastAPI `app` symbol is re-exported here so `uvicorn main:app` works
exactly like `uvicorn src.api.app:app`.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Any

from dotenv import load_dotenv

_app: Any | None = None


def _load_app() -> Any:
    """Import the FastAPI app lazily so `python main.py scrape` doesn't pull in API deps."""
    global _app
    if _app is None:
        responses = importlib.import_module("starlette.responses")
        RedirectResponse = getattr(responses, "RedirectResponse")
        api_module = importlib.import_module("src.api.app")
        fastapi_app = getattr(api_module, "app")

        @fastapi_app.get("/", include_in_schema=False)
        def _root() -> Any:
            """Redirect base URL to the versioned docs for convenience."""
            return RedirectResponse(url="/v1/docs")

        _app = fastapi_app
    return _app


def __getattr__(name: str) -> Any:
    if name == "app":
        return _load_app()
    raise AttributeError(name)


def _cmd_scrape(_args: argparse.Namespace) -> int:
    from src.scraper.prism import run

    run()
    return 0


def _cmd_api(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level.lower(),
    )
    return 0


def _cmd_index(args: argparse.Namespace) -> int:
    from src.indexing.cli import main as index_main

    forwarded: list[str] = ["--collections", args.collections, "--batch-size", str(args.batch_size)]
    if args.source:
        forwarded.extend(["--source", args.source])
    return index_main(forwarded)


def _cmd_index_prices(args: argparse.Namespace) -> int:
    from src.indexing.price_cli import main as price_index_main

    forwarded: list[str] = ["--collections", args.collections, "--batch-size", str(args.batch_size)]
    if args.source:
        forwarded.extend(["--source", args.source])
    return price_index_main(forwarded)


def _cmd_openstat(_args: argparse.Namespace) -> int:
    from src.openstat.runner import run as openstat_run

    return openstat_run()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prism", description="PRiSM scraper, indexer, and API.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("scrape", help="Run the PRiSM scraper (job selected via PRISM_JOB).")
    sub.add_parser("openstat", help="Run OpenStatv2 compatibility workflows.")

    api_parser = sub.add_parser("api", help="Start the FastAPI service via uvicorn.")
    api_parser.add_argument("--host", default="0.0.0.0")
    api_parser.add_argument("--port", type=int, default=8000)
    api_parser.add_argument("--reload", action="store_true")
    api_parser.add_argument("--log-level", default="info")

    index_parser = sub.add_parser("index", help="Index the yield CSV into Qdrant.")
    index_parser.add_argument(
        "--collections",
        choices=("all", "structured", "knowledge"),
        default="all",
    )
    index_parser.add_argument("--batch-size", type=int, default=256)
    index_parser.add_argument("--source", default=None)

    index_prices_parser = sub.add_parser("index-prices", help="Index OpenSTAT price CSV into Qdrant.")
    index_prices_parser.add_argument(
        "--collections",
        choices=("all", "structured", "knowledge"),
        default="all",
    )
    index_prices_parser.add_argument("--batch-size", type=int, default=256)
    index_prices_parser.add_argument("--source", default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command in (None, "scrape"):
        return _cmd_scrape(args)
    if args.command == "api":
        return _cmd_api(args)
    if args.command == "index":
        return _cmd_index(args)
    if args.command == "index-prices":
        return _cmd_index_prices(args)
    if args.command == "openstat":
        return _cmd_openstat(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
