"""Centralized API settings.

All environment variables are validated once at startup; the application
fails fast if anything is missing or malformed. Routes and services read
configuration exclusively through the `Settings` instance returned by
`get_settings()` — `os.getenv` is never called from request paths.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings(BaseSettings):
    """Strongly-typed runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    api_title: str = Field(default="PRiSM API")
    api_version: str = Field(default="1.0.0")
    api_docs_enabled: bool = Field(default=True)
    api_log_level: str = Field(default="INFO")
    api_log_json: bool = Field(default=True)
    api_cors_origins: str = Field(default="")

    api_keys_public: str = Field(default="")
    api_keys_admin: str = Field(default="")
    api_auth_disabled: bool = Field(default=False)

    rate_limit_read: str = Field(default="120/minute")
    rate_limit_search: str = Field(default="30/minute")
    rate_limit_export: str = Field(default="5/minute")

    export_max_rows: int = Field(default=100_000, gt=0)
    summary_cache_size: int = Field(default=256, gt=0)
    default_search_limit: int = Field(default=10, gt=0, le=100)
    default_min_score: float = Field(default=0.0, ge=0.0, le=1.0)

    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_api_key: str | None = Field(default=None)
    qdrant_timeout_seconds: float = Field(default=30.0, gt=0)
    qdrant_records_collection: str = Field(default="prism_yield_records")
    qdrant_knowledge_collection: str = Field(default="prism_yield_knowledge")
    qdrant_local_inference_batch_size: int = Field(default=128, gt=0)

    embedding_dense_model: str = Field(default="BAAI/bge-small-en-v1.5")
    embedding_sparse_model: str = Field(default="Qdrant/bm25")
    embedding_dense_size: int = Field(default=384, gt=0)

    schema_version: str = Field(default="v1")
    csv_source_relpath: str = Field(default="prism_processed/prism_yield_export.csv")

    @field_validator("api_log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        normalized = value.upper().strip()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized not in allowed:
            raise ValueError(f"api_log_level must be one of {sorted(allowed)}")
        return normalized

    @property
    def cors_origins(self) -> list[str]:
        return _split_csv(self.api_cors_origins)

    @property
    def public_keys(self) -> set[str]:
        return set(_split_csv(self.api_keys_public))

    @property
    def admin_keys(self) -> set[str]:
        return set(_split_csv(self.api_keys_admin))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance, cached for the lifetime of the app."""
    return Settings()
