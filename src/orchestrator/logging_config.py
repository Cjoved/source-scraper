"""Structured logging for orchestrator runs (P3.7)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import structlog

from src.services.config import data_path

_configured = False


def orchestrator_log_dir() -> Path:
    raw = os.getenv("ORCHESTRATOR_LOG_DIR", "data/logs").strip()
    if raw.startswith("data/"):
        return data_path(*raw.split("/")[1:])
    return Path(raw)


def orchestrator_log_json() -> bool:
    return os.getenv("ORCHESTRATOR_LOG_JSON", "true").strip().lower() in (
        "true",
        "1",
        "yes",
    )


def configure_orchestrator_logging() -> None:
    """Configure structlog; append JSON lines to data/logs/orchestrator.jsonl."""
    global _configured
    if _configured:
        return

    log_dir = orchestrator_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "orchestrator.jsonl"

    level_name = os.getenv("ORCHESTRATOR_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)

    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[file_handler, console_handler],
        force=True,
    )

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    if orchestrator_log_json():
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_orchestrator_logger(name: str = "orchestrator") -> structlog.stdlib.BoundLogger:
    configure_orchestrator_logging()
    return structlog.get_logger(name)


def bind_run_context(*, run_id: str, job_id: str) -> None:
    configure_orchestrator_logging()
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(run_id=run_id, job_id=job_id)


def clear_run_context() -> None:
    structlog.contextvars.clear_contextvars()
