"""Per-job Wasabi backup: corpus-data/latest|backup + Checkpoint/latest|backup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from src.services.config import data_path
from src.storage.wasabi_store import (
    ArtifactKind,
    WasabiConfigError,
    WasabiUploadError,
    get_s3_client,
    rotate_and_upload,
    wasabi_enabled,
)

LogFn = Callable[[str], None]


@dataclass(frozen=True)
class WasabiArtifact:
    """One local file uploaded after a successful orchestrator job."""

    local_relpath: str
    remote_filename: str
    kind: ArtifactKind


# Orchestrator job_id -> artifacts to upload (under data/).
JOB_WASABI_ARTIFACTS: dict[str, tuple[WasabiArtifact, ...]] = {
    "philrice": (
        WasabiArtifact("philrice_processed/philrice_corpus.jsonl", "philrice_corpus.jsonl", "corpus"),
        WasabiArtifact("checkpoints/philrice_checkpoint.json", "philrice_checkpoint.json", "checkpoint"),
    ),
    "philrice_news": (
        WasabiArtifact(
            "philrice_news_processed/philrice_news_corpus.jsonl",
            "philrice_news_corpus.jsonl",
            "corpus",
        ),
        WasabiArtifact(
            "checkpoints/philrice_news_checkpoint.json",
            "philrice_news_checkpoint.json",
            "checkpoint",
        ),
        WasabiArtifact(
            "checkpoints/philrice_news_scrape_status.json",
            "philrice_news_scrape_status.json",
            "checkpoint",
        ),
    ),
    "pinoyrice": (
        WasabiArtifact("pinoyrice_processed/pinoyrice_corpus.jsonl", "pinoyrice_corpus.jsonl", "corpus"),
        WasabiArtifact("checkpoints/pinoyrice_checkpoint.json", "pinoyrice_checkpoint.json", "checkpoint"),
    ),
    "irri": (
        WasabiArtifact("irri_processed/irri_corpus.jsonl", "irri_corpus.jsonl", "corpus"),
        WasabiArtifact("checkpoints/irri_checkpoint.json", "irri_checkpoint.json", "checkpoint"),
    ),
    "openstat": (
        WasabiArtifact("openstat_processed/openstat_table.csv", "openstat_table.csv", "corpus"),
        WasabiArtifact("openstat_processed/openstat_corpus.jsonl", "openstat_corpus.jsonl", "corpus"),
        WasabiArtifact("checkpoints/openstat_checkpoint.json", "openstat_checkpoint.json", "checkpoint"),
    ),
    "prism_scrape": (
        WasabiArtifact("prism_processed/prism_corpus_chunked.jsonl", "prism_corpus_chunked.jsonl", "corpus"),
        WasabiArtifact("checkpoints/prism_checkpoint.json", "prism_checkpoint.json", "checkpoint"),
    ),
    "prism_yield": (
        WasabiArtifact("prism_processed/prism_yield_export.csv", "prism_yield_export.csv", "corpus"),
        WasabiArtifact(
            "checkpoints/prism_yield_export_checkpoint.json",
            "prism_yield_export_checkpoint.json",
            "checkpoint",
        ),
    ),
}


def backup_job_artifacts(
    job_id: str,
    *,
    log: LogFn | None = None,
    require_any_upload: bool = True,
) -> list[dict[str, str]]:
    """
    Rotate latest->backup and upload local artifacts for one orchestrator job.

    Skips missing local files with a warning (e.g. optional openstat_corpus.jsonl).
    """
    if log is None:
        log = print

    if not wasabi_enabled():
        log("[dim]Wasabi backup disabled (set WASABI_ACCESS_KEY + WASABI_SECRET_KEY).[/dim]")
        return []

    artifacts = JOB_WASABI_ARTIFACTS.get(job_id)
    if not artifacts:
        log(f"[dim]No Wasabi artifact mapping for job '{job_id}'.[/dim]")
        return []

    try:
        client = get_s3_client()
    except WasabiConfigError as exc:
        raise WasabiUploadError(str(exc)) from exc

    uploaded: list[dict[str, str]] = []
    log(f"[cyan]Wasabi backup ({job_id}):[/cyan] {len(artifacts)} artifact(s)")

    for spec in artifacts:
        local_path = data_path(*spec.local_relpath.split("/"))
        if not local_path.is_file():
            log(f"  [yellow]Skip missing:[/yellow] {spec.local_relpath}")
            continue
        try:
            result = rotate_and_upload(
                local_path,
                kind=spec.kind,
                remote_filename=spec.remote_filename,
                client=client,
            )
            uploaded.append(result)
            tier = "corpus-data" if spec.kind == "corpus" else "Checkpoint"
            dated = result.get("dated", "")
            snap = result.get("snapshot_date", "")
            log(f"  [green]OK[/green] {spec.remote_filename} -> {tier}/latest/")
            if dated and snap:
                log(f"       [dim]dated snapshot: {tier}/history/{snap}/[/dim]")
        except WasabiUploadError as exc:
            raise WasabiUploadError(f"{job_id}/{spec.remote_filename}: {exc}") from exc

    if not uploaded and require_any_upload:
        raise WasabiUploadError(f"No artifacts uploaded for job '{job_id}' (all local files missing).")
    if not uploaded:
        log(f"[yellow]No local artifacts found for {job_id}; skipped.[/yellow]")

    return uploaded
