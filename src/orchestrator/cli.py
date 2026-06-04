"""CLI for the source-scraper orchestrator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from src.orchestrator.config import load_config
from src.orchestrator.jobs import run_all, run_due, run_job
from src.orchestrator.serve import serve
from src.orchestrator.schedule import next_run_time
from src.services.config import PROJECT_ROOT

console = Console()


def _cmd_list(_args: argparse.Namespace) -> int:
    cfg = load_config(Path(_args.config) if _args.config else None)
    table = Table(title="Orchestrator jobs")
    table.add_column("ID")
    table.add_column("Enabled")
    table.add_column("Cron")
    table.add_column("Browser")
    table.add_column("Next run (PH)")

    for job in cfg.jobs:
        nxt = next_run_time(job.cron, cfg.timezone)
        table.add_row(
            job.id,
            "yes" if job.enabled else "no",
            job.cron,
            "yes" if job.browser_heavy else "no",
            nxt.strftime("%Y-%m-%d %H:%M %Z"),
        )
    console.print(table)
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    config_path = Path(args.config) if args.config else None
    cfg = load_config(config_path)

    if args.all:
        return run_all(cfg)
    if args.due:
        return run_due(cfg)
    if not args.job_id:
        console.print("[red]Provide a job_id, --all, or --due.[/red]")
        return 2
    return 0 if run_job(args.job_id, cfg) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrator",
        description="Run scheduled scrape+process jobs from orchestrator.yaml",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help=f"Path to orchestrator.yaml (default: {PROJECT_ROOT / 'orchestrator.yaml'})",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="Run one or more jobs")
    run_group = run_parser.add_mutually_exclusive_group()
    run_group.add_argument("job_id", nargs="?", default=None, help="Single job id to run")
    run_group.add_argument("--all", action="store_true", help="Run all enabled jobs in safe order")
    run_group.add_argument(
        "--due",
        action="store_true",
        help="Run jobs whose cron matches the current time (Asia/Manila from yaml)",
    )
    run_parser.set_defaults(func=_cmd_run)

    list_parser = sub.add_parser("list", help="List jobs and next scheduled run")
    list_parser.set_defaults(func=_cmd_list)

    serve_parser = sub.add_parser(
        "serve",
        help="Long-running scheduler: poll run --due every interval (APScheduler)",
    )
    serve_parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Poll interval in seconds (default: 60)",
    )
    serve_parser.set_defaults(func=_cmd_serve)

    return parser


def _cmd_serve(args: argparse.Namespace) -> int:
    config_path = Path(args.config) if args.config else None
    serve(config_path, interval_seconds=args.interval)
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    return int(func(args))


if __name__ == "__main__":
    sys.exit(main())
