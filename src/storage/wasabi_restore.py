"""Restore corpus + checkpoint artifacts from Wasabi latest (or backup) tier."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from src.orchestrator.wasabi_backup import JOB_WASABI_ARTIFACTS
from src.services.config import data_path
from src.storage.wasabi_store import (
    WasabiConfigError,
    WasabiUploadError,
    download_latest,
    get_s3_client,
    list_dated_snapshots,
    wasabi_enabled,
)

LogFn = Callable[[str], None]


def list_job_snapshot_dates(job_id: str) -> list[str]:
    """Union of dated history folders across all artifacts for one job (newest first)."""
    artifacts = JOB_WASABI_ARTIFACTS.get(job_id)
    if not artifacts:
        raise ValueError(f"No Wasabi artifact mapping for job '{job_id}'.")

    dates: set[str] = set()
    for spec in artifacts:
        dates.update(list_dated_snapshots(spec.kind, spec.remote_filename))
    return sorted(dates, reverse=True)


def print_snapshot_dates(
    *,
    job_id: str | None = None,
    log: LogFn | None = None,
) -> None:
    if log is None:
        log = print

    if not wasabi_enabled():
        raise WasabiConfigError(
            "Wasabi restore disabled (set WASABI_ACCESS_KEY + WASABI_SECRET_KEY)."
        )

    if job_id:
        dates = list_job_snapshot_dates(job_id)
        log(f"[cyan]{job_id}[/cyan] dated snapshots: {', '.join(dates) if dates else '(none)'}")
        return

    for mapped_job in sorted(JOB_WASABI_ARTIFACTS):
        dates = list_job_snapshot_dates(mapped_job)
        log(f"[cyan]{mapped_job}[/cyan]: {', '.join(dates) if dates else '(none)'}")


def restore_job_artifacts(
    job_id: str,
    *,
    tier: str = "latest",
    snapshot_date: str | None = None,
    log: LogFn | None = None,
) -> list[dict[str, str]]:
    """Download mapped artifacts for one orchestrator job into data/."""
    if log is None:
        log = print

    if tier not in ("latest", "backup", "dated"):
        raise ValueError("tier must be 'latest', 'backup', or 'dated'")
    if tier == "dated" and not snapshot_date:
        raise ValueError("snapshot_date (YYYY-MM-DD) is required when tier is 'dated'")

    if not wasabi_enabled():
        raise WasabiConfigError(
            "Wasabi restore disabled (set WASABI_ACCESS_KEY + WASABI_SECRET_KEY)."
        )

    artifacts = JOB_WASABI_ARTIFACTS.get(job_id)
    if not artifacts:
        raise ValueError(f"No Wasabi artifact mapping for job '{job_id}'.")

    client = get_s3_client()
    restored: list[dict[str, str]] = []
    label = f"{tier}/{snapshot_date}" if tier == "dated" else tier
    log(f"[cyan]Wasabi restore ({job_id}, {label}):[/cyan] {len(artifacts)} artifact(s)")

    for spec in artifacts:
        local_path = data_path(*spec.local_relpath.split("/"))
        try:
            result = download_latest(
                local_path,
                kind=spec.kind,
                remote_filename=spec.remote_filename,
                tier=tier,  # type: ignore[arg-type]
                snapshot_date=snapshot_date,
                client=client,
            )
            restored.append(result)
            log(f"  [green]OK[/green] {spec.remote_filename} -> {local_path}")
        except WasabiUploadError as exc:
            log(f"  [yellow]Skip missing:[/yellow] {spec.remote_filename} ({exc})")

    if not restored:
        raise WasabiUploadError(f"No artifacts restored for job '{job_id}'.")

    return restored


def restore_all_jobs(
    *,
    tier: str = "latest",
    snapshot_date: str | None = None,
    log: LogFn | None = None,
) -> list[dict[str, str]]:
    """Restore all jobs that have Wasabi mappings (skips jobs with no remote objects)."""
    if log is None:
        log = print
    all_results: list[dict[str, str]] = []
    for mapped_job in sorted(JOB_WASABI_ARTIFACTS):
        try:
            all_results.extend(
                restore_job_artifacts(mapped_job, tier=tier, snapshot_date=snapshot_date, log=log)
            )
        except (WasabiUploadError, WasabiConfigError, ValueError) as exc:
            log(f"[yellow]Skip {mapped_job}:[/yellow] {exc}")
    if not all_results:
        raise WasabiUploadError("No artifacts restored for any job.")
    return all_results


def run_reindex_after_restore(*, log: LogFn | None = None) -> None:
    """Rebuild Qdrant from restored JSONL/CSV (yield, corpus RAG, OpenSTAT prices)."""
    if log is None:
        log = print

    from src.orchestrator.preflight import ensure_qdrant
    from src.orchestrator.runners.index_jobs import run_corpus_rag_index_job, run_openstat_index_job
    from src.orchestrator.runners.prism_jobs import run_prism_index

    if not ensure_qdrant(log=log):
        raise RuntimeError("Qdrant not available — cannot re-index after restore.")

    log("[cyan]Re-index PRiSM yield[/cyan]")
    run_prism_index()
    log("[cyan]Re-index corpus RAG[/cyan]")
    run_corpus_rag_index_job()
    log("[cyan]Re-index OpenSTAT prices[/cyan]")
    run_openstat_index_job()
    log("[green]Re-index complete.[/green]")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restore corpus/checkpoint files from Wasabi into data/."
    )
    parser.add_argument(
        "--job",
        choices=sorted(JOB_WASABI_ARTIFACTS.keys()),
        help="Orchestrator job id to restore (default: --all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Restore all mapped jobs (skips missing remote objects per job)",
    )
    parser.add_argument(
        "--list-dates",
        action="store_true",
        help="List available dated snapshot folders (YYYY-MM-DD) on Wasabi",
    )
    parser.add_argument(
        "--tier",
        choices=("latest", "backup", "dated"),
        default="latest",
        help="Wasabi tier to pull from (default: latest)",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Required when --tier dated (e.g. 2026-06-16)",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="After restore, rebuild Qdrant indexes from local JSONL/CSV",
    )
    parser.add_argument(
        "--qdrant",
        action="store_true",
        help="Restore Qdrant collection snapshots from Wasabi (skip corpus files)",
    )
    args = parser.parse_args(argv)

    if args.list_dates:
        try:
            print_snapshot_dates(job_id=args.job)
        except (WasabiConfigError, ValueError) as exc:
            print(f"[red]List dates failed:[/red] {exc}", file=sys.stderr)
            return 1
        return 0

    if not args.all and not args.job and not args.qdrant:
        parser.error("Specify --job <id>, --all, --qdrant, or --list-dates")
    if args.tier == "dated" and not args.date:
        parser.error("--date YYYY-MM-DD is required when --tier dated")
    if args.qdrant and args.reindex:
        parser.error("Use either --qdrant (snapshot restore) or --reindex (rebuild from JSONL), not both")

    try:
        if args.qdrant:
            from src.storage.qdrant_wasabi_backup import restore_qdrant_collections

            restore_qdrant_collections(tier=args.tier, snapshot_date=args.date)
        elif args.all:
            restore_all_jobs(tier=args.tier, snapshot_date=args.date)
        else:
            restore_job_artifacts(args.job, tier=args.tier, snapshot_date=args.date)
        if args.reindex:
            run_reindex_after_restore()
    except (WasabiConfigError, WasabiUploadError, ValueError, RuntimeError) as exc:
        print(f"[red]Restore failed:[/red] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
