"""Orchestrator job registry and execution."""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable
from datetime import datetime

from rich.console import Console

from src.orchestrator.alerts import send_run_alert
from src.orchestrator.config import JobSpec, OrchestratorConfig, load_config
from src.orchestrator.corpus_validation import (
    JOB_CORPUS_SOURCES,
    validate_job_corpora,
    validate_quality_enabled,
)
from src.orchestrator.env import job_env
from src.orchestrator.lock import browser_job_lock, lock_holder
from src.orchestrator.logging_config import (
    bind_run_context,
    clear_run_context,
    get_orchestrator_logger,
)
from src.orchestrator.preflight import ensure_flaresolverr, ensure_qdrant
from src.orchestrator.run_context import RunContext
from src.orchestrator.runners import (
    run_irri,
    run_openstat,
    run_philrice,
    run_philrice_news,
    run_pinoyrice,
    run_prism_scrape,
    run_prism_yield,
    run_prism_index,
)
from src.orchestrator.schedule import job_due_now

console = Console()

# P2.3 safe execution order for run --all
JOB_ORDER: tuple[str, ...] = (
    "philrice",
    "philrice_news",
    "pinoyrice",
    "irri",
    "openstat",
    "prism_scrape",
    "prism_yield",
    "prism_index",
)

_RUNNERS: dict[str, Callable[[], None]] = {
    "philrice": run_philrice,
    "philrice_news": run_philrice_news,
    "pinoyrice": run_pinoyrice,
    "irri": run_irri,
    "openstat": run_openstat,
    "prism_scrape": run_prism_scrape,
    "prism_yield": run_prism_yield,
    "prism_index": run_prism_index,
}


def validate_config(config: OrchestratorConfig) -> None:
    yaml_ids = {j.id for j in config.jobs}
    for job_id in JOB_ORDER:
        if job_id not in yaml_ids:
            raise ValueError(f"orchestrator.yaml missing job id required by JOB_ORDER: {job_id}")
    for job_id in yaml_ids:
        if job_id not in _RUNNERS:
            raise ValueError(f"No runner registered for job id: {job_id}")


def run_job(job_id: str, config: OrchestratorConfig | None = None) -> bool:
    """
    Run a single job by id. Returns True on success, False on failure.
    """
    cfg = config or load_config()
    validate_config(cfg)

    spec = cfg.job_by_id(job_id)
    if spec is None:
        console.print(f"[red]Unknown job id:[/red] {job_id}")
        console.print(f"[dim]Known ids: {', '.join(_RUNNERS)}[/dim]")
        return False

    if not spec.enabled:
        console.print(f"[yellow]Job disabled in orchestrator.yaml:[/yellow] {job_id}")
        return True

    runner = _RUNNERS[job_id]
    ctx = RunContext.start(job_id, spec, cfg)
    bind_run_context(run_id=ctx.run_id, job_id=job_id)
    log = get_orchestrator_logger().bind(event="job.lifecycle")

    console.rule(f"[bold]Orchestrator – {job_id}[/bold]")
    console.print(f"[dim]run_id={ctx.run_id} timeout_minutes={spec.timeout_minutes} browser_heavy={spec.browser_heavy}[/dim]")
    log.info("job.started", run_dir=str(ctx.run_dir))

    try:
        if spec.browser_heavy:
            holder = lock_holder()
            if holder is not None:
                other_job = holder.get("job_id", "?")
                other_pid = holder.get("pid", "?")
                reason = f"Skipped (browser lock held by job={other_job} pid={other_pid})"
                console.print(f"[yellow]{reason}[/yellow]")
                ctx.mark_skipped(reason)
                log.warning("job.skipped", reason=reason)
                return True

        if job_id == "openstat":
            if not ensure_flaresolverr(log=console.print):
                msg = "OpenSTAT preflight failed — FlareSolverr not available."
                console.print(f"[red]{msg}[/red]")
                ctx.mark_failed(message=msg, error_type="PreflightError")
                log.error("job.preflight_failed", component="flaresolverr")
                send_run_alert(ctx)
                return False

        if job_id == "prism_index":
            if not ensure_qdrant(log=console.print):
                msg = "Qdrant preflight failed — indexer cannot run."
                console.print(f"[red]{msg}[/red]")
                ctx.mark_failed(message=msg, error_type="PreflightError")
                log.error("job.preflight_failed", component="qdrant")
                send_run_alert(ctx)
                return False

        started = time.monotonic()
        success = False
        try:
            if spec.browser_heavy:
                with browser_job_lock(job_id) as acquired:
                    if not acquired:
                        holder = lock_holder() or {}
                        reason = (
                            f"Skipped (browser lock held by job={holder.get('job_id', '?')} "
                            f"pid={holder.get('pid', '?')})"
                        )
                        console.print(f"[yellow]{reason}[/yellow]")
                        ctx.mark_skipped(reason)
                        log.warning("job.skipped", reason=reason)
                        return True
                    with job_env(spec.env_overrides):
                        runner()
            else:
                with job_env(spec.env_overrides):
                    runner()

            if job_id in JOB_CORPUS_SOURCES:
                check_quality = validate_quality_enabled()
                validation = validate_job_corpora(
                    job_id, log=console.print, check_quality=check_quality
                )
                for w in validation.warnings:
                    ctx.add_warning(w)
                ctx.set_validation(
                    list(validation.reports),
                    passed=validation.passed,
                    check_quality=check_quality,
                )
                if not validation.passed:
                    console.print(f"[red]Corpus validation failed after {job_id}[/red]")
                    from src.orchestrator.corpus_validation import validation_failure_summary

                    ctx.mark_failed(
                        message=validation_failure_summary(validation.reports),
                        error_type="ValidationError",
                    )
                    log.error("validation.failed")
                    send_run_alert(ctx)
                    return False
            else:
                ctx.write_skipped_validation_report("no_corpus_mapping")

            ctx.mark_ok()
            success = True
        except Exception as exc:
            console.print(f"[red]Job failed ({job_id}):[/red] {exc}")
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            ctx.mark_failed(message=str(exc), exc=exc)
            log.exception("job.failed")
            send_run_alert(ctx)
            return False
        finally:
            elapsed = time.monotonic() - started
            elapsed_min = elapsed / 60.0
            if elapsed_min > spec.timeout_minutes:
                warn = (
                    f"Job {job_id} exceeded configured timeout "
                    f"({elapsed_min:.1f}m > {spec.timeout_minutes}m)"
                )
                console.print(f"[yellow]Warning: {warn}[/yellow]")
                ctx.add_warning(warn)
                log.warning("job.timeout_exceeded", elapsed_minutes=round(elapsed_min, 1))

        if success:
            console.print(f"[green]Job completed:[/green] {job_id}")
            log.info("job.completed", status="ok")
            send_run_alert(ctx)
        return success
    finally:
        clear_run_context()


def run_all(config: OrchestratorConfig | None = None) -> int:
    """Run all enabled jobs in JOB_ORDER. Returns exit code (0 ok, 1 any failure)."""
    cfg = config or load_config()
    validate_config(cfg)

    failed: list[str] = []
    skipped: list[str] = []

    for job_id in JOB_ORDER:
        spec = cfg.job_by_id(job_id)
        if spec is None or not spec.enabled:
            skipped.append(job_id)
            continue
        if not run_job(job_id, cfg):
            failed.append(job_id)

    console.rule("[bold]Orchestrator – run --all summary[/bold]")
    if skipped:
        console.print(f"[dim]Skipped (disabled/missing):[/dim] {', '.join(skipped)}")
    if failed:
        console.print(f"[red]Failed:[/red] {', '.join(failed)}")
        return 1
    console.print("[green]All jobs completed successfully.[/green]")
    return 0


def run_due(config: OrchestratorConfig | None = None, now: datetime | None = None) -> int:
    """Run enabled jobs whose cron matches now in the configured timezone."""
    cfg = config or load_config()
    validate_config(cfg)

    due_jobs: list[JobSpec] = []
    for job in cfg.enabled_jobs():
        if job_due_now(job.cron, cfg.timezone, now=now):
            due_jobs.append(job)

    if not due_jobs:
        console.print("[dim]No jobs due at this time.[/dim]")
        return 0

    console.print(
        f"[cyan]Due jobs ({cfg.timezone}):[/cyan] {', '.join(j.id for j in due_jobs)}"
    )

    due_ids = {j.id for j in due_jobs}
    failed: list[str] = []
    for job_id in JOB_ORDER:
        if job_id not in due_ids:
            continue
        if not run_job(job_id, cfg):
            failed.append(job_id)

    if failed:
        console.print(f"[red]Due run failures:[/red] {', '.join(failed)}")
        return 1
    return 0
