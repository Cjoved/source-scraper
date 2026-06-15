"""FastAPI dependency providers.

These functions are imported via `Depends(...)` so test suites can replace
storage and metadata cache with in-memory fakes via `app.dependency_overrides`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import Depends

from src.api.metadata_cache import MetadataCache
from src.api.settings import Settings, get_settings
from src.services.config import data_path
from src.storage.qdrant_store import QdrantStoreProtocol


@lru_cache(maxsize=1)
def _metadata_cache_singleton() -> MetadataCache:
    return MetadataCache()


def get_metadata_cache() -> MetadataCache:
    return _metadata_cache_singleton()


@lru_cache(maxsize=1)
def _qdrant_store_singleton() -> QdrantStoreProtocol:
    from src.storage.qdrant_store import QdrantStore

    return QdrantStore(get_settings())


def get_qdrant_store(
    _settings: Settings = Depends(get_settings),
) -> QdrantStoreProtocol:
    return _qdrant_store_singleton()


def get_csv_source_path(settings: Settings = Depends(get_settings)) -> Path:
    parts = settings.csv_source_relpath.split("/")
    return data_path(*parts)


def get_openstat_csv_path(settings: Settings = Depends(get_settings)) -> Path:
    parts = settings.openstat_csv_source_relpath.split("/")
    return data_path(*parts)


@lru_cache(maxsize=1)
def _price_metadata_cache_singleton() -> "PriceMetadataCache":
    from src.api.price_metadata_cache import PriceMetadataCache

    return PriceMetadataCache()


def get_price_metadata_cache() -> "PriceMetadataCache":
    return _price_metadata_cache_singleton()


def reset_dependency_singletons() -> None:
    """Test helper: clear cached singletons so each test sees a fresh state."""
    _metadata_cache_singleton.cache_clear()
    _price_metadata_cache_singleton.cache_clear()
    _qdrant_store_singleton.cache_clear()
    get_settings.cache_clear()
