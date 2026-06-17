"""Centralized lazy imports for optional ``qdrant-client``.

Install for API/indexing: ``uv sync --extra api``
Install for orchestrator + Qdrant Wasabi backup: ``uv sync --extra orchestrator --extra api``
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from qdrant_client import QdrantClient as QdrantClientType

_INSTALL_HINT = "uv sync --extra api (or --extra orchestrator --extra api for Wasabi Qdrant backup)"


class QdrantClientNotInstalledError(ImportError):
    """Raised when qdrant-client is required but the optional dependency is missing."""


@lru_cache(maxsize=1)
def _client_class() -> type[Any]:
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise QdrantClientNotInstalledError(
            f"qdrant-client is required. Install with: {_INSTALL_HINT}"
        ) from exc
    return QdrantClient


@lru_cache(maxsize=1)
def models() -> Any:
    """Return ``qdrant_client.models`` (lazy import)."""
    try:
        from qdrant_client import models as qdrant_models
    except ImportError as exc:
        raise QdrantClientNotInstalledError(
            f"qdrant-client is required. Install with: {_INSTALL_HINT}"
        ) from exc
    return qdrant_models


def create_qdrant_client(
    *,
    url: str,
    api_key: str | None = None,
    timeout: int = 30,
    local_inference_batch_size: int | None = None,
) -> Any:
    """Construct a basic ``QdrantClient`` (snapshots, preflight, etc.)."""
    cls = _client_class()
    kwargs: dict[str, Any] = {
        "url": url,
        "api_key": api_key,
        "timeout": timeout,
    }
    if local_inference_batch_size is not None:
        kwargs["local_inference_batch_size"] = local_inference_batch_size
    return cls(**kwargs)


def create_store_client(settings: Any) -> Any:
    """Construct a ``QdrantClient`` configured for :class:`QdrantStore`."""
    client = create_qdrant_client(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        timeout=int(settings.qdrant_timeout_seconds),
        local_inference_batch_size=settings.qdrant_local_inference_batch_size,
    )
    client.set_model(settings.embedding_dense_model)
    client.set_sparse_model(settings.embedding_sparse_model)
    return client
