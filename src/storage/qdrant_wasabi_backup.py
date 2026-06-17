"""Create Qdrant collection snapshots and upload them to Wasabi."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from src.api.settings import get_settings
from src.storage.qdrant_imports import create_qdrant_client
from src.storage.wasabi_store import (
    WasabiConfigError,
    WasabiUploadError,
    download_latest,
    get_s3_client,
    rotate_and_upload,
    wasabi_enabled,
)

LogFn = Callable[[str], None]

_INDEX_JOB_IDS = frozenset({"corpus_rag_index", "prism_index", "openstat_index"})


def qdrant_collection_names() -> list[str]:
    settings = get_settings()
    return [
        settings.qdrant_records_collection,
        settings.qdrant_knowledge_collection,
        settings.qdrant_price_records_collection,
        settings.qdrant_price_knowledge_collection,
        settings.corpus_rag_collection,
    ]


def _qdrant_headers() -> dict[str, str]:
    settings = get_settings()
    headers: dict[str, str] = {}
    if settings.qdrant_api_key:
        headers["api-key"] = settings.qdrant_api_key
    return headers


def _get_qdrant_client() -> Any:
    settings = get_settings()
    return create_qdrant_client(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=int(settings.qdrant_timeout_seconds),
    )


def _existing_collections(client: Any) -> set[str]:
    return {collection.name for collection in client.get_collections().collections}


def _download_snapshot_file(collection_name: str, snapshot_name: str, dest: Path) -> None:
    settings = get_settings()
    base = settings.qdrant_url.rstrip("/")
    url = f"{base}/collections/{collection_name}/snapshots/{snapshot_name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(
        url,
        headers=_qdrant_headers(),
        stream=True,
        timeout=settings.qdrant_timeout_seconds,
    ) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def backup_qdrant_collections(
    *,
    log: LogFn | None = None,
    qdrant_client: Any | None = None,
    s3_client: Any | None = None,
    require_any: bool = False,
) -> list[dict[str, str]]:
    """
    Snapshot each existing Qdrant collection and upload to ``qdrant-data/`` on Wasabi.

    When *require_any* is True (post-index jobs), at least one collection must upload
    successfully or a :class:`WasabiUploadError` is raised.
    """
    if log is None:
        log = print

    if not wasabi_enabled():
        log("[dim]Wasabi disabled — skipping Qdrant backup.[/dim]")
        return []

    client = qdrant_client or _get_qdrant_client()
    s3 = s3_client or get_s3_client()
    existing = _existing_collections(client)
    targets = [name for name in qdrant_collection_names() if name in existing]
    missing = [name for name in qdrant_collection_names() if name not in existing]

    log(f"[cyan]Qdrant Wasabi backup:[/cyan] {len(targets)} collection(s)")
    for name in missing:
        log(f"  [dim]Skip missing collection:[/dim] {name}")

    if not targets:
        if require_any:
            raise WasabiUploadError("No Qdrant collections exist to back up.")
        log("[yellow]No Qdrant collections found — skipped Qdrant backup.[/yellow]")
        return []

    uploaded: list[dict[str, str]] = []
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="qdrant_snap_") as tmp:
        work = Path(tmp)
        for collection_name in targets:
            remote_filename = f"{collection_name}.snapshot"
            local_path = work / remote_filename
            snapshot_name = ""
            try:
                snapshot = client.create_snapshot(collection_name=collection_name)
                snapshot_name = snapshot.name
                _download_snapshot_file(collection_name, snapshot_name, local_path)
                if not local_path.is_file() or local_path.stat().st_size == 0:
                    raise WasabiUploadError(f"Empty snapshot file for {collection_name}")
                result = rotate_and_upload(
                    local_path,
                    kind="qdrant",
                    remote_filename=remote_filename,
                    client=s3,
                )
                uploaded.append(result)
                dated = result.get("dated", "")
                snap = result.get("snapshot_date", "")
                log(f"  [green]OK[/green] {collection_name} -> qdrant-data/latest/{remote_filename}")
                if dated and snap:
                    log(f"       [dim]dated snapshot: qdrant-data/history/{snap}/[/dim]")
            except Exception as exc:
                failures.append(f"{collection_name}: {exc}")
                log(f"  [yellow]Skip failed snapshot:[/yellow] {collection_name} ({exc})")
            finally:
                if snapshot_name:
                    try:
                        client.delete_snapshot(
                            collection_name=collection_name,
                            snapshot_name=snapshot_name,
                        )
                    except Exception:
                        pass

    if require_any and not uploaded:
        details = "\n".join(failures) if failures else "No collections uploaded."
        raise WasabiUploadError(f"Qdrant backup produced no uploads.\n{details}")
    if failures and require_any:
        raise WasabiUploadError("Qdrant backup failed for:\n" + "\n".join(failures))

    return uploaded


def should_backup_qdrant_after_job(job_id: str) -> bool:
    return job_id in _INDEX_JOB_IDS


def restore_qdrant_collections(
    *,
    tier: str = "latest",
    snapshot_date: str | None = None,
    log: LogFn | None = None,
    s3_client: Any | None = None,
) -> list[dict[str, str]]:
    """Download Qdrant snapshots from Wasabi and recover each collection."""
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

    s3 = s3_client or get_s3_client()
    label = f"{tier}/{snapshot_date}" if tier == "dated" else tier
    log(f"[cyan]Qdrant Wasabi restore ({label}):[/cyan] {len(qdrant_collection_names())} collection(s)")

    restored: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="qdrant_restore_") as tmp:
        work = Path(tmp)
        for collection_name in qdrant_collection_names():
            remote_filename = f"{collection_name}.snapshot"
            local_path = work / remote_filename
            try:
                result = download_latest(
                    local_path,
                    kind="qdrant",
                    remote_filename=remote_filename,
                    tier=tier,  # type: ignore[arg-type]
                    snapshot_date=snapshot_date,
                    client=s3,
                )
            except WasabiUploadError as exc:
                log(f"  [yellow]Skip missing:[/yellow] {remote_filename} ({exc})")
                continue
            _upload_snapshot_to_qdrant(collection_name, local_path)
            restored.append(result)
            log(f"  [green]OK[/green] {collection_name} <- {remote_filename}")

    if not restored:
        raise WasabiUploadError("No Qdrant snapshots restored from Wasabi.")

    return restored


def _upload_snapshot_to_qdrant(collection_name: str, snapshot_path: Path) -> None:
    settings = get_settings()
    base = settings.qdrant_url.rstrip("/")
    url = f"{base}/collections/{collection_name}/snapshots/upload"
    with snapshot_path.open("rb") as handle:
        response = requests.post(
            url,
            headers=_qdrant_headers(),
            files={"snapshot": (snapshot_path.name, handle, "application/octet-stream")},
            timeout=settings.qdrant_timeout_seconds,
        )
    response.raise_for_status()
