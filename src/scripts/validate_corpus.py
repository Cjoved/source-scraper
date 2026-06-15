"""
Validate CPT JSONL corpus files against docs/DATA_FORMAT_SPEC.md.

Usage (from project root):

    uv run python -m src.scripts.validate_corpus
    uv run python -m src.scripts.validate_corpus --source philrice
    uv run python -m src.scripts.validate_corpus --path data/philrice_processed/philrice_corpus.jsonl
    uv run python -m src.scripts.validate_corpus --quality --strict
    uv run python -m src.scripts.validate_corpus --json-out data/runs/validation_report.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.indexing.corpus_manifest import RAG_CORPUS_SOURCES
from src.services.config import PROJECT_ROOT, data_path
from src.utils.jsonl import iter_jsonl_records

REQUIRED_KEYS = ("text", "input", "source", "doc_id")
CORE_STRING_KEYS = ("text", "input", "source", "doc_id", "content", "url", "title", "filename")
OPTIONAL_INT_KEYS = ("page",)


@dataclass(frozen=True)
class CorpusSource:
    """One registered JSONL output."""

    id: str
    relpath: str
    description: str = ""
    # Per-source min text length when --quality; None = VALIDATE_MIN_TEXT_CHARS (default 100).
    min_text_chars: int | None = None


# RAG sources from corpus_manifest (P3.8a); extras are validation-only (not indexed).
_EXTRA_VALIDATION_SOURCES: tuple[CorpusSource, ...] = (
    CorpusSource(
        "openstat_lines",
        "openstat_processed/openstat_corpus.jsonl",
        "OpenSTAT line-level CPT (not RAG-indexed)",
        min_text_chars=80,
    ),
    CorpusSource("pinoyrice_chunked", "pinoyrice_processed/pinoyrice_corpus_chunked.jsonl", "PinoyRice chunked"),
    CorpusSource("pinoyrice_pdfs", "pinoyrice_processed/pinoyrice_pdfs_corpus.jsonl", "PinoyRice PDFs"),
    CorpusSource("prism", "prism_processed/prism_corpus.jsonl", "PRiSM browser raw"),
)

_CORPUS_SOURCES_FROM_RAG: tuple[CorpusSource, ...] = tuple(
    CorpusSource(
        rag.source_id,
        rag.relpath,
        rag.description,
        min_text_chars=rag.min_text_chars,
    )
    for rag in RAG_CORPUS_SOURCES
)

# Keep in sync with docs/DATA_FORMAT_SPEC.md
CORPUS_SOURCES: tuple[CorpusSource, ...] = _CORPUS_SOURCES_FROM_RAG + _EXTRA_VALIDATION_SOURCES

SOURCE_BY_ID = {s.id: s for s in CORPUS_SOURCES}


@dataclass
class FileReport:
    source_id: str
    path: str
    status: str  # ok | failed | skipped
    records: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    empty_lines: int = 0
    physical_lines: int = 0
    duplicate_doc_ids: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _validate_record(
    obj: object,
    line_no: int,
    *,
    min_text_chars: int,
    doc_ids_seen: dict[str, int],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(obj, dict):
        return [f"Line {line_no}: expected JSON object, got {type(obj).__name__}"]

    for key in REQUIRED_KEYS:
        if key not in obj:
            errors.append(f"Line {line_no}: missing required key '{key}'")
        elif not isinstance(obj[key], str):
            errors.append(f"Line {line_no}: key '{key}' must be string")
        elif not str(obj[key]).strip():
            errors.append(f"Line {line_no}: key '{key}' is empty")

    for key in CORE_STRING_KEYS:
        if key in obj and obj[key] is not None and not isinstance(obj[key], str):
            errors.append(f"Line {line_no}: key '{key}' must be string when present")

    text = obj.get("text") if isinstance(obj.get("text"), str) else ""
    inp = obj.get("input") if isinstance(obj.get("input"), str) else ""
    if text and inp and text != inp:
        errors.append(f"Line {line_no}: 'text' and 'input' must be identical")

    content = obj.get("content")
    if content is not None and isinstance(content, str) and text and content != text:
        errors.append(f"Line {line_no}: 'content' must equal 'text' when present")

    if text and len(text.strip()) < min_text_chars:
        errors.append(
            f"Line {line_no}: text shorter than min length ({len(text.strip())} < {min_text_chars})"
        )

    for key in OPTIONAL_INT_KEYS:
        if key in obj and obj[key] is not None and not isinstance(obj[key], int):
            errors.append(f"Line {line_no}: key '{key}' must be integer when present")

    doc_id = obj.get("doc_id")
    if isinstance(doc_id, str) and doc_id.strip():
        doc_ids_seen[doc_id] = doc_ids_seen.get(doc_id, 0) + 1

    return errors


def validate_jsonl_file(
    path: Path,
    *,
    source_id: str,
    min_text_chars: int = 1,
    max_empty_line_pct: float = 100.0,
    check_quality: bool = False,
    max_errors: int = 50,
) -> FileReport:
    report = FileReport(source_id=source_id, path=str(path), status="failed")

    if not path.is_file():
        report.status = "skipped"
        report.warnings.append(f"File not found: {path}")
        return report

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        report.errors.append(f"Cannot read file: {exc}")
        return report

    if not raw_text.strip():
        report.errors.append("File is empty")
        return report

    # Count JSONL record lines by newline only (not splitlines — PDF text may contain U+0085/U+2028).
    raw_lines = raw_text.split("\n")
    report.physical_lines = len(raw_lines)
    report.empty_lines = sum(1 for line in raw_lines if not line.strip())
    doc_ids_seen: dict[str, int] = {}
    min_chars = min_text_chars if check_quality else 1

    try:
        parsed = list(iter_jsonl_records(path))
    except OSError as exc:
        report.errors.append(f"Cannot read file: {exc}")
        return report

    for start_line, obj, end_line in parsed:
        report.records += 1
        if end_line > start_line:
            report.warnings.append(
                f"Record at line {start_line} spans physical lines {start_line}-{end_line} "
                "(run compact_jsonl to normalize)"
            )
        if not isinstance(obj, dict):
            report.errors.append(f"Line {start_line}: expected JSON object, got {type(obj).__name__}")
        else:
            report.errors.extend(
                _validate_record(
                    obj,
                    start_line,
                    min_text_chars=min_chars,
                    doc_ids_seen=doc_ids_seen,
                )
            )

        if len(report.errors) >= max_errors:
            report.errors.append(f"... truncated after {max_errors} errors")
            break

    non_empty_lines = report.physical_lines - report.empty_lines
    if non_empty_lines > report.records:
        report.warnings.append(
            f"Non-empty newline-separated lines ({non_empty_lines}) exceed parsed records "
            f"({report.records}); file may contain split JSONL lines — run compact_jsonl"
        )
    elif non_empty_lines < report.records:
        report.warnings.append(
            f"Parsed records ({report.records}) exceed non-empty lines ({non_empty_lines}); "
            "check for embedded Unicode line separators (U+0085/U+2028) — run compact_jsonl --sanitize"
        )

    if report.records == 0 and not any("invalid JSON" in e for e in report.errors):
        report.errors.append("No valid JSON records found")

    if check_quality and report.physical_lines > 0:
        empty_pct = 100.0 * report.empty_lines / report.physical_lines
        if empty_pct > max_empty_line_pct:
            report.errors.append(
                f"Empty-line ratio {empty_pct:.1f}% exceeds max {max_empty_line_pct:.1f}%"
            )

    if check_quality:
        report.duplicate_doc_ids = [d for d, n in doc_ids_seen.items() if n > 1]
        for doc_id in report.duplicate_doc_ids[:20]:
            report.errors.append(f"Duplicate doc_id: {doc_id} ({doc_ids_seen[doc_id]} occurrences)")
        if len(report.duplicate_doc_ids) > 20:
            report.errors.append(
                f"... and {len(report.duplicate_doc_ids) - 20} more duplicate doc_ids"
            )

    report.status = "ok" if not report.errors else "failed"
    return report


def resolve_sources(
    *,
    source_filter: str | None,
    path_arg: Path | None,
) -> list[tuple[CorpusSource, Path]]:
    if path_arg is not None:
        resolved = path_arg.resolve()
        try:
            rel = str(resolved.relative_to(PROJECT_ROOT.resolve()))
        except ValueError:
            rel = resolved.name
        return [(CorpusSource("custom", rel, "custom path"), resolved)]

    selected = CORPUS_SOURCES
    if source_filter:
        if source_filter not in SOURCE_BY_ID:
            known = ", ".join(SOURCE_BY_ID)
            raise ValueError(f"Unknown source id '{source_filter}'. Known: {known}")
        selected = (SOURCE_BY_ID[source_filter],)

    return [(spec, data_path(*spec.relpath.split("/"))) for spec in selected]


def reports_to_json_payload(
    reports: list[FileReport],
    *,
    quality_checks: bool = False,
    strict: bool = False,
) -> dict[str, object]:
    """Machine-readable validation report (P3.4)."""
    return {
        "spec": "docs/DATA_FORMAT_SPEC.md",
        "quality_checks": quality_checks,
        "strict": strict,
        "files": [
            {
                "source_id": r.source_id,
                "path": r.path,
                "status": r.status,
                "records": r.records,
                "errors": r.errors,
                "warnings": r.warnings,
                "empty_lines": r.empty_lines,
                "physical_lines": r.physical_lines,
                "duplicate_doc_ids": r.duplicate_doc_ids,
            }
            for r in reports
        ],
    }


def run_validation(
    *,
    source_filter: str | None = None,
    path_arg: Path | None = None,
    strict: bool = False,
    check_quality: bool = False,
    max_errors: int = 50,
) -> tuple[list[FileReport], int]:
    min_text_chars = int(os.getenv("VALIDATE_MIN_TEXT_CHARS", "100"))
    max_empty_pct = float(os.getenv("VALIDATE_MAX_EMPTY_LINE_PCT", "5"))

    reports: list[FileReport] = []
    for spec, path in resolve_sources(source_filter=source_filter, path_arg=path_arg):
        source_min = spec.min_text_chars if spec.min_text_chars is not None else min_text_chars
        rep = validate_jsonl_file(
            path,
            source_id=spec.id,
            min_text_chars=source_min,
            max_empty_line_pct=max_empty_pct,
            check_quality=check_quality,
            max_errors=max_errors,
        )
        if rep.status == "skipped" and strict:
            rep.status = "failed"
            rep.errors.append("Missing file (--strict)")
        reports.append(rep)

    exit_code = 0
    for rep in reports:
        if rep.status == "failed":
            exit_code = 1
        elif rep.status == "skipped" and strict:
            exit_code = 1
    return reports, exit_code


def _print_reports(reports: list[FileReport]) -> None:
    from rich.console import Console

    console = Console()
    for rep in reports:
        if rep.status == "ok":
            style = "green"
        elif rep.status == "skipped":
            style = "yellow"
        else:
            style = "red"
        console.print(f"\n[{style}]{rep.status.upper()}[/{style}] {rep.source_id}: {rep.path}")
        if rep.status != "skipped":
            console.print(
                f"  records={rep.records} empty_lines={rep.empty_lines}/{rep.physical_lines}"
            )
        for w in rep.warnings:
            console.print(f"  [dim]warn:[/dim] {w}")
        for e in rep.errors:
            console.print(f"  - {e}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate CPT JSONL corpus files (see docs/DATA_FORMAT_SPEC.md).",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help=f"Validate one source id: {', '.join(SOURCE_BY_ID)}",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Validate a single JSONL file (bypass source registry)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail if a registered corpus file is missing",
    )
    parser.add_argument(
        "--quality",
        action="store_true",
        help="Enable P3.5-style checks (min length, empty-line %%, duplicate doc_id)",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=50,
        help="Stop collecting errors per file after this many (default: 50)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write machine-readable report JSON (for P3.4 runs folder)",
    )
    args = parser.parse_args(argv)

    try:
        reports, exit_code = run_validation(
            source_filter=args.source,
            path_arg=args.path,
            strict=args.strict,
            check_quality=args.quality,
            max_errors=args.max_errors,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    _print_reports(reports)

    if args.json_out:
        payload = reports_to_json_payload(
            reports,
            quality_checks=args.quality,
            strict=args.strict,
        )
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote report: {args.json_out}")

    ok_count = sum(1 for r in reports if r.ok)
    fail_count = sum(1 for r in reports if r.status == "failed")
    skip_count = sum(1 for r in reports if r.status == "skipped")
    print(f"\nSummary: ok={ok_count} failed={fail_count} skipped={skip_count}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
