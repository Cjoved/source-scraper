"""Local FlashRank reranker with fail-open behavior."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_RERANK_TEXT_CHARS = 1500
_ranker_lock = threading.Lock()
_ranker: Any | None = None
_ranker_failed = False


@dataclass(frozen=True)
class RerankResult:
    ordered_indexes: list[int]
    scores: list[float]
    available: bool
    warning: str | None = None


def _cache_dir() -> str:
    override = os.getenv("FASTEMBED_CACHE_PATH") or os.getenv("FLASHRANK_CACHE_DIR")
    if override:
        path = Path(override) / "flashrank"
    else:
        path = Path.home() / ".cache" / "flashrank"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _get_ranker() -> Any | None:
    global _ranker, _ranker_failed
    if _ranker_failed:
        return None
    if _ranker is not None:
        return _ranker
    with _ranker_lock:
        if _ranker_failed:
            return None
        if _ranker is not None:
            return _ranker
        try:
            from flashrank import Ranker

            try:
                _ranker = Ranker(cache_dir=_cache_dir())
            except TypeError:
                # Older flashrank versions may not require cache_dir.
                _ranker = Ranker()
        except Exception:
            _ranker_failed = True
            return None
        return _ranker


def reset_ranker_for_tests() -> None:
    """Clear singleton state (unit tests only)."""
    global _ranker, _ranker_failed
    with _ranker_lock:
        _ranker = None
        _ranker_failed = False


def candidate_text(payload: dict[str, Any], *, max_chars: int = _RERANK_TEXT_CHARS) -> str:
    parts: list[str] = []
    for key in ("title", "snippet", "text", "content", "input"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    text = "\n".join(parts).strip() or str(payload.get("doc_id") or payload.get("filename") or "")
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def rerank_texts(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    top_k: int | None = None,
    enabled: bool = True,
) -> RerankResult:
    """Rerank candidate dicts that include ``text`` (and optional ``id``).

    Returns original order on failure or when disabled (fail-open).
    """
    n = len(candidates)
    if n == 0:
        return RerankResult(ordered_indexes=[], scores=[], available=True)
    limit = n if top_k is None else max(0, min(top_k, n))
    identity = list(range(n))
    identity_scores = [float(c.get("score") or 0.0) for c in candidates]

    if not enabled or not query.strip():
        return RerankResult(
            ordered_indexes=identity[:limit],
            scores=identity_scores[:limit],
            available=True,
        )

    ranker = _get_ranker()
    if ranker is None:
        return RerankResult(
            ordered_indexes=identity[:limit],
            scores=identity_scores[:limit],
            available=False,
            warning="FlashRank unavailable; using original retrieval order.",
        )

    passages: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        text = str(candidate.get("text") or "").strip()
        if not text:
            text = f"candidate-{index}"
        passages.append({"id": index, "text": text})

    try:
        from flashrank import RerankRequest

        request = RerankRequest(query=query.strip(), passages=passages)
        ranked = ranker.rerank(request)
    except Exception:
        return RerankResult(
            ordered_indexes=identity[:limit],
            scores=identity_scores[:limit],
            available=False,
            warning="FlashRank rerank failed; using original retrieval order.",
        )

    ordered_indexes: list[int] = []
    scores: list[float] = []
    seen: set[int] = set()
    for item in ranked:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        if raw_id is None:
            continue
        try:
            idx = int(raw_id)
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= n or idx in seen:
            continue
        seen.add(idx)
        ordered_indexes.append(idx)
        try:
            scores.append(float(item.get("score") or 0.0))
        except (TypeError, ValueError):
            scores.append(0.0)
        if len(ordered_indexes) >= limit:
            break

    # Append any missing candidates to preserve completeness.
    for idx in identity:
        if len(ordered_indexes) >= limit:
            break
        if idx not in seen:
            ordered_indexes.append(idx)
            scores.append(identity_scores[idx])

    return RerankResult(
        ordered_indexes=ordered_indexes[:limit],
        scores=scores[:limit],
        available=True,
    )


def rerank_hit_payloads(
    query: str,
    hits: list[Any],
    *,
    top_k: int,
    enabled: bool = True,
) -> tuple[list[Any], RerankResult]:
    """Rerank store hit records that expose ``.payload`` and ``.score``."""
    candidates: list[dict[str, Any]] = []
    for hit in hits:
        payload = dict(getattr(hit, "payload", None) or {})
        candidates.append(
            {
                "text": candidate_text(payload),
                "score": float(getattr(hit, "score", 0.0) or 0.0),
            }
        )
    result = rerank_texts(query, candidates, top_k=top_k, enabled=enabled)
    ordered = [hits[i] for i in result.ordered_indexes]
    # Attach rerank score onto a shallow copy when possible.
    out: list[Any] = []
    for hit, score in zip(ordered, result.scores, strict=False):
        payload = dict(getattr(hit, "payload", None) or {})
        cls = type(hit)
        try:
            out.append(cls(score=float(score), payload=payload))
        except Exception:
            out.append(hit)
    return out, result
