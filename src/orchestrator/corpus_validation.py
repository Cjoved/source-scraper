"""Post-job corpus validation (P3.2) — wire P3.1 validator into orchestrator runs."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.scripts.validate_corpus import FileReport, run_validation
from src.services.config import data_path

LogFn = Callable[[str], None]

# Orchestrator job_id → validate_corpus source id(s) produced by scrape+process.
# Jobs not listed (prism_yield, prism_index) have no JSONL corpus to validate.
JOB_CORPUS_SOURCES: dict[str, tuple[str, ...]] = {
    "philrice": ("philrice",),
    "philrice_news": ("philrice_news",),
    "pinoyrice": ("pinoyrice", "pinoyrice_pdfs"),
    "irri": ("irri",),
    "openstat": ("openstat",),
    "prism_scrape": ("prism_chunked",),
}

# Optional sources: validate when file exists; warn if missing (not a failure).
OPTIONAL_CORPUS_SOURCES: dict[str, frozenset[str]] = {
    "pinoyrice": frozenset({"pinoyrice_pdfs"}),
}


def validate_quality_enabled() -> bool:
    return os.getenv("ORCHESTRATOR_VALIDATE_QUALITY", "true").strip().lower() in (
        "true",
        "1",
        "yes",
    )


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    reports: tuple[FileReport, ...]
    sources_checked: tuple[str, ...]
    warnings: tuple[str, ...]


def validation_failure_summary(reports: tuple[FileReport, ...] | list[FileReport]) -> str:
    """One-line summary for alerts and logs when corpus validation fails."""
    for rep in reports:
        if rep.status == "ok":
            continue
        if rep.errors:
            return f"Corpus validation failed — {rep.source_id}: {rep.errors[0]}"
        return f"Corpus validation failed — {rep.source_id} ({rep.status})"
    return "Corpus validation failed"


def _resolve_source_path(source_id: str) -> Path:
    from src.scripts.validate_corpus import SOURCE_BY_ID

    spec = SOURCE_BY_ID[source_id]
    return data_path(*spec.relpath.split("/"))


def validate_job_corpora(
    job_id: str,
    *,
    log: LogFn | None = None,
    check_quality: bool | None = None,
) -> ValidationResult:
    """
    Validate JSONL outputs for an orchestrator job.

    Returns ValidationResult with all FileReports. Uses strict=True for required
    sources; optional sources skip when file is missing.
    """
    if log is None:
        log = print

    source_ids = JOB_CORPUS_SOURCES.get(job_id)
    if not source_ids:
        return ValidationResult(passed=True, reports=(), sources_checked=(), warnings=())

    if check_quality is None:
        check_quality = validate_quality_enabled()

    optional = OPTIONAL_CORPUS_SOURCES.get(job_id, frozenset())
    log(f"[cyan]Corpus validation ({job_id}):[/cyan] {', '.join(source_ids)}")
    all_reports: list[FileReport] = []
    extra_warnings: list[str] = []
    all_ok = True

    for source_id in source_ids:
        path = _resolve_source_path(source_id)
        is_optional = source_id in optional
        if is_optional and not path.is_file():
            msg = f"Optional corpus not present, skipped: {source_id} ({path})"
            extra_warnings.append(msg)
            log(f"  [dim]{msg}[/dim]")
            continue

        reports, exit_code = run_validation(
            source_filter=source_id,
            strict=not is_optional,
            check_quality=check_quality,
        )
        for rep in reports:
            _log_report(rep, log=log)
            if rep.status != "ok":
                all_ok = False
        if exit_code != 0:
            all_ok = False
        all_reports.extend(reports)

    return ValidationResult(
        passed=all_ok,
        reports=tuple(all_reports),
        sources_checked=source_ids,
        warnings=tuple(extra_warnings),
    )


def _log_report(rep: FileReport, *, log: LogFn) -> None:
    if rep.status == "ok":
        log(f"  [green]OK[/green] {rep.source_id}: {rep.records} records — {rep.path}")
        return
    if rep.status == "skipped":
        log(f"  [yellow]SKIP[/yellow] {rep.source_id}: {rep.path}")
        for w in rep.warnings:
            log(f"    {w}")
        return
    log(f"  [red]FAIL[/red] {rep.source_id}: {rep.path}")
    for e in rep.errors[:15]:
        log(f"    - {e}")
    if len(rep.errors) > 15:
        log(f"    ... {len(rep.errors) - 15} more errors")
