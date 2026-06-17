"""Wasabi (S3-compatible) upload helpers for corpus + checkpoint artifacts."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ArtifactKind = Literal["corpus", "checkpoint", "qdrant"]
ObjectTier = Literal["latest", "backup", "dated"]

_HISTORY_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class WasabiConfigError(RuntimeError):
    """Missing or invalid Wasabi configuration."""


class WasabiUploadError(RuntimeError):
    """Upload or rotate operation failed."""


def wasabi_enabled() -> bool:
    raw = os.getenv("WASABI_ENABLED", "").strip().lower()
    if raw in ("false", "0", "no"):
        return False
    if raw in ("true", "1", "yes"):
        return True
    return bool(os.getenv("WASABI_ACCESS_KEY", "").strip() and os.getenv("WASABI_SECRET_KEY", "").strip())


def backup_fail_job() -> bool:
    return os.getenv("WASABI_BACKUP_FAIL_JOB", "true").strip().lower() in ("true", "1", "yes")


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise WasabiConfigError(f"Missing required env var: {name}")
    return value


def wasabi_settings() -> dict[str, str]:
    return {
        "access_key": _require_env("WASABI_ACCESS_KEY"),
        "secret_key": _require_env("WASABI_SECRET_KEY"),
        "bucket": os.getenv("WASABI_BUCKET", "agent-scraper").strip() or "agent-scraper",
        "region": os.getenv("WASABI_REGION", "ap-southeast-1").strip() or "ap-southeast-1",
        "endpoint": os.getenv(
            "WASABI_ENDPOINT",
            "https://s3.ap-southeast-1.wasabisys.com",
        ).strip(),
        "corpus_prefix": _normalize_prefix(os.getenv("WASABI_CORPUS_PREFIX", "corpus-data/")),
        "checkpoint_prefix": _normalize_prefix(os.getenv("WASABI_CHECKPOINT_PREFIX", "Checkpoint/")),
        "qdrant_prefix": _normalize_prefix(os.getenv("WASABI_QDRANT_PREFIX", "qdrant-data/")),
    }


def _normalize_prefix(prefix: str) -> str:
    prefix = prefix.strip().replace("\\", "/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return prefix


def dated_retention_count() -> int:
    """How many date-stamped history copies to keep per file (default 2)."""
    raw = os.getenv("WASABI_DATED_RETENTION", "2").strip()
    try:
        value = int(raw)
    except ValueError:
        return 2
    return max(1, value)


def _prefix_for_kind(kind: ArtifactKind) -> str:
    settings = wasabi_settings()
    if kind == "corpus":
        return settings["corpus_prefix"]
    if kind == "checkpoint":
        return settings["checkpoint_prefix"]
    return settings["qdrant_prefix"]


def object_key(
    kind: ArtifactKind,
    tier: ObjectTier,
    filename: str,
    *,
    snapshot_date: str | None = None,
) -> str:
    """S3 key for latest, backup, or dated history (``history/YYYY-MM-DD/``)."""
    base = _prefix_for_kind(kind)
    name = filename.lstrip("/")
    if tier == "dated":
        if not snapshot_date or not _HISTORY_DATE_RE.match(snapshot_date):
            raise WasabiUploadError(f"Invalid snapshot date (use YYYY-MM-DD): {snapshot_date!r}")
        return f"{base}history/{snapshot_date}/{name}"
    return f"{base}{tier}/{name}"


def get_s3_client() -> Any:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise WasabiConfigError(
            "boto3 is required for Wasabi uploads. Install with: uv sync --extra orchestrator"
        ) from exc

    settings = wasabi_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings["endpoint"],
        aws_access_key_id=settings["access_key"],
        aws_secret_access_key=settings["secret_key"],
        region_name=settings["region"],
        config=Config(signature_version="s3v4"),
    )


def _object_exists(client: Any, bucket: str, key: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise WasabiUploadError(f"head_object failed for s3://{bucket}/{key}: {exc}") from exc


def _list_dated_history_keys(
    client: Any,
    bucket: str,
    kind: ArtifactKind,
    remote_filename: str,
) -> list[tuple[str, str]]:
    """Return (YYYY-MM-DD, s3_key) for history copies of *remote_filename*, newest first."""
    base = _prefix_for_kind(kind)
    prefix = f"{base}history/"
    name = remote_filename.lstrip("/")
    matches: list[tuple[str, str]] = []

    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = str(obj["Key"])
            suffix = key[len(prefix) :]
            if "/" not in suffix:
                continue
            date_part, fname = suffix.split("/", 1)
            if fname != name or not _HISTORY_DATE_RE.match(date_part):
                continue
            matches.append((date_part, key))

    matches.sort(key=lambda item: item[0], reverse=True)
    return matches


def _prune_dated_history(
    client: Any,
    bucket: str,
    kind: ArtifactKind,
    remote_filename: str,
    *,
    retention: int | None = None,
) -> list[str]:
    """Delete oldest dated history objects beyond *retention* count."""
    keep = retention if retention is not None else dated_retention_count()
    dated_keys = _list_dated_history_keys(client, bucket, kind, remote_filename)
    deleted: list[str] = []
    for _date, key in dated_keys[keep:]:
        client.delete_object(Bucket=bucket, Key=key)
        deleted.append(key)
    return deleted


def rotate_and_upload(
    local_path: Path,
    *,
    kind: ArtifactKind,
    remote_filename: str,
    client: Any | None = None,
    snapshot_date: str | None = None,
) -> dict[str, str]:
    """
    Copy existing latest object to backup (if present), upload to latest, and
    add a dated copy under ``history/YYYY-MM-DD/``. Prunes old dated copies
    beyond ``WASABI_DATED_RETENTION`` (default 2).

    Returns S3 keys touched.
    """
    if not local_path.is_file():
        raise WasabiUploadError(f"Local file not found: {local_path}")

    settings = wasabi_settings()
    bucket = settings["bucket"]
    s3 = client or get_s3_client()
    date_str = snapshot_date or datetime.now(UTC).strftime("%Y-%m-%d")

    latest = object_key(kind, "latest", remote_filename)
    backup = object_key(kind, "backup", remote_filename)
    dated = object_key(kind, "dated", remote_filename, snapshot_date=date_str)

    if _object_exists(s3, bucket, latest):
        s3.copy_object(
            Bucket=bucket,
            Key=backup,
            CopySource={"Bucket": bucket, "Key": latest},
        )

    s3.upload_file(str(local_path), bucket, latest)
    s3.upload_file(str(local_path), bucket, dated)
    pruned = _prune_dated_history(s3, bucket, kind, remote_filename)

    return {
        "local": str(local_path),
        "latest": f"s3://{bucket}/{latest}",
        "backup": f"s3://{bucket}/{backup}",
        "dated": f"s3://{bucket}/{dated}",
        "snapshot_date": date_str,
        "pruned_dated_keys": ",".join(pruned),
        "kind": kind,
        "remote_filename": remote_filename,
    }


def download_latest(
    local_path: Path,
    *,
    kind: ArtifactKind,
    remote_filename: str,
    tier: ObjectTier = "latest",
    snapshot_date: str | None = None,
    client: Any | None = None,
) -> dict[str, str]:
    """Download one object from Wasabi latest, backup, or dated history tier."""
    settings = wasabi_settings()
    bucket = settings["bucket"]
    s3 = client or get_s3_client()
    key = object_key(kind, tier, remote_filename, snapshot_date=snapshot_date)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        s3.download_file(bucket, key, str(local_path))
    except Exception as exc:
        from botocore.exceptions import ClientError

        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                raise WasabiUploadError(f"Object not found: s3://{bucket}/{key}") from exc
        raise WasabiUploadError(f"download failed for s3://{bucket}/{key}: {exc}") from exc
    return {
        "local": str(local_path),
        "remote": f"s3://{bucket}/{key}",
        "kind": kind,
        "remote_filename": remote_filename,
        "tier": tier,
        "snapshot_date": snapshot_date or "",
    }


def list_dated_snapshots(
    kind: ArtifactKind,
    remote_filename: str,
    *,
    client: Any | None = None,
) -> list[str]:
    """List available YYYY-MM-DD history dates for one remote file (newest first)."""
    settings = wasabi_settings()
    s3 = client or get_s3_client()
    return [date for date, _key in _list_dated_history_keys(s3, settings["bucket"], kind, remote_filename)]
