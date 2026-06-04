"""Load orchestrator.yaml into typed job configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.services.config import PROJECT_ROOT

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "orchestrator.yaml"


@dataclass(frozen=True)
class JobSpec:
    id: str
    enabled: bool
    cron: str
    browser_heavy: bool
    env_overrides: dict[str, str]
    timeout_minutes: int


@dataclass(frozen=True)
class OrchestratorConfig:
    timezone: str
    default_timeout_minutes: int
    jobs: tuple[JobSpec, ...]

    def job_by_id(self, job_id: str) -> JobSpec | None:
        for job in self.jobs:
            if job.id == job_id:
                return job
        return None

    def enabled_jobs(self) -> list[JobSpec]:
        return [j for j in self.jobs if j.enabled]


def _parse_job(raw: dict[str, Any], default_timeout: int) -> JobSpec:
    job_id = str(raw["id"])
    env = raw.get("env_overrides") or {}
    if not isinstance(env, dict):
        raise ValueError(f"Job {job_id}: env_overrides must be a mapping")
    return JobSpec(
        id=job_id,
        enabled=bool(raw.get("enabled", True)),
        cron=str(raw["cron"]),
        browser_heavy=bool(raw.get("browser_heavy", False)),
        env_overrides={str(k): str(v) for k, v in env.items()},
        timeout_minutes=int(raw.get("timeout_minutes", default_timeout)),
    )


def load_config(path: Path | None = None) -> OrchestratorConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise FileNotFoundError(f"Orchestrator config not found: {config_path}")

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("orchestrator.yaml must be a mapping at the top level")

    defaults = data.get("defaults") or {}
    default_timeout = int(defaults.get("timeout_minutes", 180))
    jobs_raw = data.get("jobs")
    if not isinstance(jobs_raw, list) or not jobs_raw:
        raise ValueError("orchestrator.yaml must define a non-empty jobs list")

    jobs = tuple(_parse_job(item, default_timeout) for item in jobs_raw)
    ids = [j.id for j in jobs]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate job id in orchestrator.yaml")

    return OrchestratorConfig(
        timezone=str(data.get("timezone", "Asia/Manila")),
        default_timeout_minutes=default_timeout,
        jobs=jobs,
    )
