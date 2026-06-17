"""Phase 5 release + Wasabi backup jobs (P5.1–P5.5)."""

from __future__ import annotations

from rich.console import Console

console = Console()

_PHASE5_MSG = (
    "Phase 5 not implemented yet — see AUTOMATION_TASKLIST.txt (P5.1–P5.5) "
    "and docs/SCHEDULER_SETUP.md § Production delivery."
)


def run_corpus_release() -> None:
    """Build data/releases/YYYY-MM-DD/ bundle + RELEASE_NOTES.md (P5.1, P5.2, P5.5)."""
    raise NotImplementedError(_PHASE5_MSG)


def run_corpus_backup_wasabi() -> None:
    """Legacy monthly job — per-job backup runs after each scrape job (see wasabi_backup.py)."""
    from src.orchestrator.wasabi_backup import JOB_WASABI_ARTIFACTS, backup_job_artifacts
    from src.storage.wasabi_store import wasabi_enabled

    if not wasabi_enabled():
        console.print("[yellow]Wasabi not configured — set WASABI_ACCESS_KEY and WASABI_SECRET_KEY.[/yellow]")
        return

    console.rule("[bold cyan]Wasabi full sync (all mapped jobs)[/bold cyan]")
    for job_id in JOB_WASABI_ARTIFACTS:
        try:
            backup_job_artifacts(job_id, log=console.print)
        except Exception as exc:
            console.print(f"[yellow]{job_id}: {exc}[/yellow]")
    console.rule("[bold green]Done[/bold green]")
