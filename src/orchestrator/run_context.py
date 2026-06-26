"""Per-job run context: manifest + validation report under data/runs/."""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from src.orchestrator.config import JobSpec, OrchestratorConfig
from src.scripts.validate_corpus import FileReport, reports_to_json_payload
from src.services.config import data_path

RunStatus = Literal["running", "ok", "failed", "skipped"]

RUNS_DIR = data_path("runs")


def make_run_id(job_id: str, *, now: datetime | None = None) -> str:
    ts = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    safe_job = job_id.replace("/", "_")
    return f"{ts}_{safe_job}"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


@dataclass
class RunContext:
    """Tracks one orchestrator job invocation and writes run artifacts."""

    run_id: str
    job_id: str
    spec: JobSpec
    config: OrchestratorConfig
    run_dir: Path
    status: RunStatus = "running"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    warnings: list[str] = field(default_factory=list)
    error: dict[str, str] | None = None
    validation_reports: list[FileReport] = field(default_factory=list)
    validation_passed: bool | None = None
    corpus_index: dict[str, Any] | None = None
    wasabi_backup: list[dict[str, str]] | None = None
    skip_reason: str | None = None
    error_explanation: dict[str, Any] | None = None

    @classmethod
    def start(
        cls,
        job_id: str,
        spec: JobSpec,
        config: OrchestratorConfig,
        *,
        now: datetime | None = None,
    ) -> RunContext:
        run_id = make_run_id(job_id, now=now)
        run_dir = RUNS_DIR / run_id
        ctx = cls(
            run_id=run_id,
            job_id=job_id,
            spec=spec,
            config=config,
            run_dir=run_dir,
        )
        ctx._write_manifest()
        return ctx

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "manifest.json"

    @property
    def validation_report_path(self) -> Path:
        return self.run_dir / "validation_report.json"

    def mark_skipped(self, reason: str) -> None:
        self.status = "skipped"
        self.skip_reason = reason
        self.warnings.append(reason)
        self._finish()

    def mark_failed(
        self,
        *,
        message: str,
        exc: BaseException | None = None,
        error_type: str = "JobError",
    ) -> None:
        self.status = "failed"
        self.error = {
            "type": error_type if exc is None else type(exc).__name__,
            "message": message,
        }
        if exc is not None:
            self.error["traceback"] = traceback.format_exc()
        self._finish()

    def mark_ok(self) -> None:
        self.status = "ok"
        self._finish()

    def set_validation(
        self,
        reports: list[FileReport],
        *,
        passed: bool,
        check_quality: bool = False,
    ) -> None:
        self.validation_reports = reports
        self.validation_passed = passed
        self._write_validation_report(check_quality=check_quality)
        self._write_manifest()

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)
        self._write_manifest()

    def set_corpus_index(self, stats: dict[str, Any]) -> None:
        self.corpus_index = stats
        self._write_manifest()

    def set_wasabi_backup(self, uploads: list[dict[str, str]]) -> None:
        self.wasabi_backup = uploads
        self._write_manifest()

    def set_error_explanation(self, explanation: dict[str, Any]) -> None:
        self.error_explanation = explanation
        self._write_manifest()

    def _finish(self) -> None:
        self.ended_at = datetime.now(UTC)
        self.duration_seconds = round(
            (self.ended_at - self.started_at).total_seconds(), 2
        )
        self._write_manifest()

    def _output_entries(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for rep in self.validation_reports:
            path = Path(rep.path)
            size = path.stat().st_size if path.is_file() else 0
            empty_pct = (
                round(100.0 * rep.empty_lines / rep.physical_lines, 2)
                if rep.physical_lines > 0
                else 0.0
            )
            entries.append(
                {
                    "source_id": rep.source_id,
                    "path": rep.path,
                    "records": rep.records,
                    "file_size_bytes": size,
                    "status": rep.status,
                    "quality": {
                        "empty_line_pct": empty_pct,
                        "duplicate_doc_ids_count": len(rep.duplicate_doc_ids),
                    },
                }
            )
        return entries

    def manifest_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "duration_seconds": self.duration_seconds,
            "orchestrator": {
                "timezone": self.config.timezone,
                "timeout_minutes": self.spec.timeout_minutes,
                "browser_heavy": self.spec.browser_heavy,
                "env_overrides": dict(self.spec.env_overrides),
            },
            "outputs": self._output_entries(),
            "warnings": list(self.warnings),
        }
        if self.skip_reason:
            payload["skip_reason"] = self.skip_reason
        if self.validation_passed is not None:
            payload["validation"] = {
                "passed": self.validation_passed,
                "sources_checked": [r.source_id for r in self.validation_reports],
            }
        if self.corpus_index is not None:
            payload["corpus_index"] = self.corpus_index
        if self.wasabi_backup is not None:
            payload["wasabi_backup"] = self.wasabi_backup
        if self.error:
            payload["error"] = self.error
        if self.error_explanation:
            payload["error_explanation"] = self.error_explanation
        return payload

    def _write_manifest(self) -> None:
        _atomic_write_json(self.manifest_path, self.manifest_dict())

    def _write_validation_report(self, *, check_quality: bool = False) -> None:
        if not self.validation_reports and self.validation_passed is None:
            return
        payload = reports_to_json_payload(
            self.validation_reports,
            quality_checks=check_quality,
            strict=True,
        )
        payload["run_id"] = self.run_id
        payload["job_id"] = self.job_id
        _atomic_write_json(self.validation_report_path, payload)

    def write_skipped_validation_report(self, reason: str) -> None:
        payload = {
            "skipped": True,
            "reason": reason,
            "run_id": self.run_id,
            "job_id": self.job_id,
        }
        _atomic_write_json(self.validation_report_path, payload)
