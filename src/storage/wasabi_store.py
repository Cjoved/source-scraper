"""Wasabi (S3-compatible) upload helpers for corpus + checkpoint artifacts."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

ArtifactKind = Literal["corpus", "checkpoint"]


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
    }


def _normalize_prefix(prefix: str) -> str:
    prefix = prefix.strip().replace("\\", "/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return prefix


def object_key(kind: ArtifactKind, tier: Literal["latest", "backup"], filename: str) -> str:
    settings = wasabi_settings()
    base = settings["corpus_prefix"] if kind == "corpus" else settings["checkpoint_prefix"]
    name = filename.lstrip("/")
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


def rotate_and_upload(
    local_path: Path,
    *,
    kind: ArtifactKind,
    remote_filename: str,
    client: Any | None = None,
) -> dict[str, str]:
    """
    Copy existing latest object to backup (if present), then upload local file to latest.

    Returns S3 keys touched.
    """
    if not local_path.is_file():
        raise WasabiUploadError(f"Local file not found: {local_path}")

    settings = wasabi_settings()
    bucket = settings["bucket"]
    s3 = client or get_s3_client()

    latest = object_key(kind, "latest", remote_filename)
    backup = object_key(kind, "backup", remote_filename)

    if _object_exists(s3, bucket, latest):
        s3.copy_object(
            Bucket=bucket,
            Key=backup,
            CopySource={"Bucket": bucket, "Key": latest},
        )

    s3.upload_file(str(local_path), bucket, latest)

    return {
        "local": str(local_path),
        "latest": f"s3://{bucket}/{latest}",
        "backup": f"s3://{bucket}/{backup}",
        "kind": kind,
        "remote_filename": remote_filename,
    }


def download_latest(
    local_path: Path,
    *,
    kind: ArtifactKind,
    remote_filename: str,
    tier: Literal["latest", "backup"] = "latest",
    client: Any | None = None,
) -> dict[str, str]:
    """Download one object from Wasabi latest or backup tier into local_path."""
    settings = wasabi_settings()
    bucket = settings["bucket"]
    s3 = client or get_s3_client()
    key = object_key(kind, tier, remote_filename)
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
    }
