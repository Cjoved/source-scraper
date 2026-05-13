"""Shared test helpers for building the FastAPI app with offline fakes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _ensure_env_defaults() -> None:
    os.environ.setdefault("API_AUTH_DISABLED", "true")
    os.environ.setdefault("API_KEYS_PUBLIC", "pub-test-key")
    os.environ.setdefault("API_KEYS_ADMIN", "adm-test-key")
    os.environ.setdefault("API_LOG_JSON", "false")
    os.environ.setdefault("API_DOCS_ENABLED", "false")


def build_test_app(seed_rows: list[dict[str, Any]] | None = None) -> tuple[FastAPI, Any]:
    """Construct a FastAPI app wired to an in-memory fake store.

    Returns the app and the fake store so tests can introspect state.
    """
    _ensure_env_defaults()

    from src.api.app import create_app
    from src.api.deps import (
        get_metadata_cache,
        get_qdrant_store,
        reset_dependency_singletons,
    )
    from src.api.metadata_cache import MetadataCache, build_snapshot_from_rows
    from src.api.settings import get_settings
    from tests.fakes.fake_store import FakeQdrantStore

    reset_dependency_singletons()
    get_settings.cache_clear()

    fake = FakeQdrantStore()
    if seed_rows:
        fake.seed(seed_rows)

    cache = MetadataCache()
    if seed_rows:
        cache.set(build_snapshot_from_rows(seed_rows))

    app = create_app()
    app.dependency_overrides[get_qdrant_store] = lambda: fake
    app.dependency_overrides[get_metadata_cache] = lambda: cache

    return app, fake


def make_client(seed_rows: list[dict[str, Any]] | None = None) -> tuple[TestClient, Any]:
    app, fake = build_test_app(seed_rows)
    return TestClient(app), fake


def sample_rows() -> list[dict[str, Any]]:
    return [
        {
            "year": 2019,
            "semester_code": 1,
            "semester_label": "1st Semester (Sept16-Mar15)",
            "region": "CAR",
            "province": "Abra",
            "municipality": "Bangued",
            "avg_yield_ton_ha": 3.0,
            "scraped_at": "2026-05-08T11:04:25",
            "source": "prism_yield_export",
            "schema_version": "v1",
        },
        {
            "year": 2019,
            "semester_code": 2,
            "semester_label": "2nd Semester (Mar16-Sept15)",
            "region": "CAR",
            "province": "Abra",
            "municipality": "Bucay",
            "avg_yield_ton_ha": 4.0,
            "scraped_at": "2026-05-08T11:04:25",
            "source": "prism_yield_export",
            "schema_version": "v1",
        },
        {
            "year": 2020,
            "semester_code": 1,
            "semester_label": "1st Semester (Sept16-Mar15)",
            "region": "CAR",
            "province": "Apayao",
            "municipality": "Calanasan",
            "avg_yield_ton_ha": 2.5,
            "scraped_at": "2026-05-08T11:04:25",
            "source": "prism_yield_export",
            "schema_version": "v1",
        },
        {
            "year": 2020,
            "semester_code": 2,
            "semester_label": "2nd Semester (Mar16-Sept15)",
            "region": "Region I",
            "province": "Ilocos Norte",
            "municipality": "Laoag",
            "avg_yield_ton_ha": 5.2,
            "scraped_at": "2026-05-08T11:04:25",
            "source": "prism_yield_export",
            "schema_version": "v1",
        },
    ]
