"""Long-running scheduler process (APScheduler) for orchestrator due jobs."""

from __future__ import annotations

import signal
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from rich.console import Console

from src.orchestrator.config import OrchestratorConfig, load_config
from src.orchestrator.jobs import run_due
from src.orchestrator.schedule import next_run_time

console = Console()


def _tick_due_jobs(config_path: Path | None) -> None:
    cfg = load_config(config_path)
    exit_code = run_due(cfg)
    if exit_code != 0:
        console.print("[yellow]Due tick finished with failures (see logs above).[/yellow]")


def serve(config_path: Path | None = None, interval_seconds: int = 60) -> None:
    """Run a blocking scheduler that polls run_due every interval_seconds."""
    cfg: OrchestratorConfig = load_config(config_path)

    console.rule("[bold]Orchestrator serve[/bold]")
    console.print(f"[dim]timezone={cfg.timezone} poll_interval={interval_seconds}s[/dim]")
    for job in cfg.jobs:
        if not job.enabled:
            continue
        nxt = next_run_time(job.cron, cfg.timezone)
        console.print(
            f"  [cyan]{job.id}[/cyan] cron={job.cron} next={nxt.strftime('%Y-%m-%d %H:%M %Z')}"
        )

    scheduler = BlockingScheduler(timezone=cfg.timezone)

    def _job_wrapper() -> None:
        _tick_due_jobs(config_path)

    scheduler.add_job(
        _job_wrapper,
        "interval",
        seconds=interval_seconds,
        id="orchestrator_due_poll",
        max_instances=1,
        coalesce=True,
    )

    def _shutdown(signum: int, _frame: object) -> None:
        console.print(f"\n[dim]Shutdown signal {signum}; stopping scheduler...[/dim]")
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, _shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _shutdown)

    console.print("[green]Scheduler started. Press Ctrl+C to stop.[/green]")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        console.print("[dim]Orchestrator serve stopped.[/dim]")
