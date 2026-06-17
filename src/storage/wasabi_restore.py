"""Restore corpus + checkpoint artifacts from Wasabi latest (or backup) tier."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from src.orchestrator.wasabi_backup import JOB_WASABI_ARTIFACTS, WasabiArtifact
from src.services.config import data_path
from src.storage.wasabi_store import (
    WasabiConfigError,
    WasabiUploadError,
    download_latest,
    get_s3_client,
    wasabi_enabled,
)

LogFn = Callable[[str], None]


def restore_job_artifacts(
    job_id: str,
    *,
    tier: str = "latest",
    log: LogFn | None = None,
) -> list[dict[str, str]]:
    """Download mapped artifacts for one orchestrator job into data/."""
    if log is None:
        log = print

    if tier not in ("latest", "backup"):
        raise ValueError("tier must be 'latest' or 'backup'")

    if not wasabi_enabled():
        raise WasabiConfigError(
            "Wasabi restore disabled (set WASABI_ACCESS_KEY + WASABI_SECRET_KEY)."
        )

    artifacts = JOB_WASABI_ARTIFACTS.get(job_id)
    if not artifacts:
        raise ValueError(f"No Wasabi artifact mapping for job '{job_id}'.")

    client = get_s3_client()
    restored: list[dict[str, str]] = []
    log(f"[cyan]Wasabi restore ({job_id}, {tier}):[/cyan] {len(artifacts)} artifact(s)")

    for spec in artifacts:
        local_path = data_path(*spec.local_relpath.split("/"))
        try:
            result = download_latest(
                local_path,
                kind=spec.kind,
                remote_filename=spec.remote_filename,
                tier=tier,  # type: ignore[arg-type]
                client=client,
            )
            restored.append(result)
            log(f"  [green]OK[/green] {spec.remote_filename} -> {local_path}")
        except WasabiUploadError as exc:
            log(f"  [yellow]Skip missing:[/yellow] {spec.remote_filename} ({exc})")

    if not restored:
        raise WasabiUploadError(f"No artifacts restored for job '{job_id}'.")

    return restored


def restore_all_jobs(*, tier: str = "latest", log: LogFn | None = None) -> list[dict[str, str]]:
    """Restore all jobs that have Wasabi mappings (skips jobs with no remote objects)."""
    if log is None:
        log = print
    all_results: list[dict[str, str]] = []
    for job_id in sorted(JOB_WASABI_ARTIFACTS):
        try:
            all_results.extend(restore_job_artifacts(job_id, tier=tier, log=log))
        except (WasabiUploadError, WasabiConfigError, ValueError) as exc:
            log(f"[yellow]Skip {job_id}:[/yellow] {exc}")
    if not all_results:
        raise WasabiUploadError("No artifacts restored for any job.")
    return all_results


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
        "--tier",
        choices=("latest", "backup"),
        default="latest",
        help="Wasabi tier to pull from (default: latest)",
    )
    args = parser.parse_args(argv)

    if not args.all and not args.job:
        parser.error("Specify --job <id> or --all")

    try:
        if args.all:
            restore_all_jobs(tier=args.tier)
        else:
            restore_job_artifacts(args.job, tier=args.tier)
    except (WasabiConfigError, WasabiUploadError, ValueError) as exc:
        print(f"[red]Restore failed:[/red] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
