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
    """Monthly full sync: all corpus/checkpoint artifacts + Qdrant collection snapshots."""
    from src.orchestrator.wasabi_backup import JOB_WASABI_ARTIFACTS, backup_job_artifacts
    from src.storage.qdrant_wasabi_backup import backup_qdrant_collections
    from src.storage.wasabi_store import WasabiUploadError, wasabi_enabled

    if not wasabi_enabled():
        raise WasabiUploadError(
            "Wasabi not configured — set WASABI_ACCESS_KEY and WASABI_SECRET_KEY."
        )

    failures: list[str] = []
    console.rule("[bold cyan]Wasabi full sync (corpus + checkpoints)[/bold cyan]")
    for job_id in JOB_WASABI_ARTIFACTS:
        try:
            backup_job_artifacts(job_id, log=console.print, require_any_upload=False)
        except WasabiUploadError as exc:
            failures.append(f"{job_id}: {exc}")

    console.rule("[bold cyan]Wasabi full sync (Qdrant snapshots)[/bold cyan]")
    try:
        backup_qdrant_collections(log=console.print, require_any=False)
    except WasabiUploadError as exc:
        failures.append(f"qdrant: {exc}")

    if failures:
        raise WasabiUploadError("Wasabi full sync failed:\n" + "\n".join(failures))

    console.rule("[bold green]Wasabi full sync complete[/bold green]")
