"""Unified RAG corpus indexer (P3.8b/c).

Reads CPT JSONL sources from :mod:`corpus_manifest` and upserts hybrid
embeddings into ``agri_corpus_rag``.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.api.settings import Settings, get_settings
from src.indexing.corpus_manifest import (
    RAG_CORPUS_SOURCES,
    RagCorpusSource,
    resolve_rag_sources,
)
from src.storage.qdrant_store import (
    CorpusPoint,
    QdrantStore,
    QdrantStoreProtocol,
    build_corpus_point_id,
)
from src.utils.jsonl import iter_jsonl_records


@dataclass
class SourceIndexStats:
    read: int = 0
    indexed: int = 0
    skipped: int = 0
    missing: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class CorpusIndexStats:
    sources: dict[str, SourceIndexStats] = field(default_factory=dict)

    @property
    def total_indexed(self) -> int:
        return sum(s.indexed for s in self.sources.values())

    def to_dict(self) -> dict[str, dict[str, Any]]:
        return {
            source_id: {
                "read": stats.read,
                "indexed": stats.indexed,
                "skipped": stats.skipped,
                "missing": stats.missing,
                "warnings": stats.warnings,
            }
            for source_id, stats in self.sources.items()
        }


def _format_elapsed(seconds: float) -> str:
    total = int(seconds)
    if total < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{secs:02d}s"


def _chunked(items: Iterable[Any], size: int) -> Iterator[list[Any]]:
    batch: list[Any] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def record_to_payload(record: dict[str, Any], source_id: str) -> dict[str, Any] | None:
    """Map a CPT JSONL record to a Qdrant payload. Returns None if text is empty."""
    text = str(record.get("text") or "").strip()
    if not text:
        return None

    doc_id = str(record.get("doc_id") or "").strip()
    if not doc_id:
        return None

    payload: dict[str, Any] = {
        "text": text,
        "source_id": source_id,
        "doc_id": doc_id,
    }
    for key in ("url", "title", "filename"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value.strip()
    page = record.get("page")
    if isinstance(page, int):
        payload["page"] = page
    return payload


def record_to_corpus_point(record: dict[str, Any], source_id: str) -> CorpusPoint | None:
    payload = record_to_payload(record, source_id)
    if payload is None:
        return None
    point_id = build_corpus_point_id(source_id, str(payload["doc_id"]))
    return CorpusPoint(point_id=point_id, text=str(payload["text"]), payload=payload)


def _log_source_progress(
    source_id: str,
    *,
    indexed: int,
    read: int,
    batch_count: int,
    elapsed: float,
) -> None:
    rate = indexed / elapsed if elapsed > 0 else 0.0
    print(
        f"[{source_id}] indexed={indexed} read={read} "
        f"(+{batch_count} batch, {rate:.1f} rec/s, elapsed {_format_elapsed(elapsed)})",
        flush=True,
    )


def index_source(
    *,
    spec: RagCorpusSource,
    path: Path,
    store: QdrantStoreProtocol,
    batch_size: int,
    dry_run: bool,
    progress: bool = False,
) -> SourceIndexStats:
    stats = SourceIndexStats()
    if not path.is_file():
        stats.missing = True
        if spec.required:
            stats.warnings.append(f"Required corpus file not found: {path}")
        else:
            stats.warnings.append(f"Optional corpus file not found (skipped): {path}")
        return stats

    started = time.monotonic()
    if progress:
        size_mb = path.stat().st_size / (1024 * 1024)
        print(
            f"[{spec.source_id}] starting {path.name} ({size_mb:.1f} MB, batch_size={batch_size})",
            flush=True,
        )

    batch: list[CorpusPoint] = []
    for _start, obj, _end in iter_jsonl_records(path):
        stats.read += 1
        if not isinstance(obj, dict):
            stats.skipped += 1
            continue
        point = record_to_corpus_point(obj, spec.source_id)
        if point is None:
            stats.skipped += 1
            continue
        batch.append(point)
        if len(batch) >= batch_size:
            batch_count = len(batch)
            if not dry_run:
                stats.indexed += store.upsert_corpus(batch)
            else:
                stats.indexed += batch_count
            if progress:
                _log_source_progress(
                    spec.source_id,
                    indexed=stats.indexed,
                    read=stats.read,
                    batch_count=batch_count,
                    elapsed=time.monotonic() - started,
                )
            batch = []

    if batch:
        batch_count = len(batch)
        if not dry_run:
            stats.indexed += store.upsert_corpus(batch)
        else:
            stats.indexed += batch_count
        if progress:
            _log_source_progress(
                spec.source_id,
                indexed=stats.indexed,
                read=stats.read,
                batch_count=batch_count,
                elapsed=time.monotonic() - started,
            )

    if progress:
        elapsed = time.monotonic() - started
        print(
            f"[{spec.source_id}] done: indexed={stats.indexed} read={stats.read} "
            f"skipped={stats.skipped} elapsed {_format_elapsed(elapsed)}",
            flush=True,
        )

    return stats


def run_corpus_rag_index(
    *,
    store: QdrantStoreProtocol | None = None,
    settings: Settings | None = None,
    source_filter: str | None = None,
    batch_size: int = 512,
    dry_run: bool = False,
    recreate_collection: bool = False,
    progress: bool = False,
) -> CorpusIndexStats:
    """Index all (or one) RAG corpus JSONL sources into Qdrant."""
    cfg = settings or get_settings()
    qdrant = store or QdrantStore(cfg)
    result = CorpusIndexStats()
    run_started = time.monotonic()

    if not dry_run:
        qdrant.ensure_corpus_collection(recreate=recreate_collection)

    sources = resolve_rag_sources(source_filter=source_filter)
    if progress:
        print(f"Indexing {len(sources)} corpus source(s)...", flush=True)

    for spec, path in sources:
        stats = index_source(
            spec=spec,
            path=path,
            store=qdrant,
            batch_size=batch_size,
            dry_run=dry_run,
            progress=progress,
        )
        result.sources[spec.source_id] = stats

    required_by_id = {r.source_id: r.required for r in RAG_CORPUS_SOURCES}
    required_missing = [
        sid
        for sid, s in result.sources.items()
        if s.missing and required_by_id.get(sid, False)
    ]
    if required_missing:
        raise FileNotFoundError(
            f"Required RAG corpus files missing for: {', '.join(required_missing)}"
        )

    if result.total_indexed == 0:
        raise RuntimeError("No corpus records indexed — all sources empty or missing")

    if progress:
        elapsed = time.monotonic() - run_started
        print(
            f"Corpus index complete: total_indexed={result.total_indexed} "
            f"elapsed {_format_elapsed(elapsed)}",
            flush=True,
        )

    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Index CPT JSONL corpora into unified Qdrant collection agri_corpus_rag.",
    )
    parser.add_argument(
        "--source",
        type=str,
        default=None,
        help="Index one source id only (see corpus_manifest.RAG_SOURCE_BY_ID).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=512,
        help="Records per upsert batch.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count records without writing to Qdrant.",
    )
    parser.add_argument(
        "--recreate-collection",
        action="store_true",
        help="Delete and recreate agri_corpus_rag before indexing.",
    )
    args = parser.parse_args(argv)

    try:
        stats = run_corpus_rag_index(
            source_filter=args.source,
            batch_size=args.batch_size,
            dry_run=args.dry_run,
            recreate_collection=args.recreate_collection,
            progress=True,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    for source_id, source_stats in stats.sources.items():
        print(
            f"{source_id}: read={source_stats.read} indexed={source_stats.indexed} "
            f"skipped={source_stats.skipped} missing={source_stats.missing}"
        )
        for warning in source_stats.warnings:
            print(f"  warn: {warning}")

    print(f"total_indexed={stats.total_indexed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
