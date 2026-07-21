"""Structured logging configuration and request-id middleware."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.api.settings import Settings

_REQUEST_ID_HEADER = "X-Request-ID"


def configure_logging(settings: Settings) -> None:
    """Configure stdlib + structlog for the application."""
    logging.basicConfig(level=settings.api_log_level, format="%(message)s")

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    if settings.api_log_json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.api_log_level),
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name) if name else structlog.get_logger()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a request id and emit a structured access log line per request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or uuid.uuid4().hex
        log = get_logger("api.access").bind(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            took_ms = round((time.perf_counter() - started) * 1000, 2)
            log.exception("request.failed", took_ms=took_ms)
            raise
        else:
            took_ms = round((time.perf_counter() - started) * 1000, 2)
            response.headers[_REQUEST_ID_HEADER] = request_id
            if request.url.path == "/api/notifications/unread-count":
                log.info(
                    "request.unknown_client",
                    status=response.status_code,
                    took_ms=took_ms,
                    client_host=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    referer=request.headers.get("referer"),
                    origin=request.headers.get("origin"),
                    host=request.headers.get("host"),
                )
            else:
                log.info("request.completed", status=response.status_code, took_ms=took_ms)
            return response
        finally:
            structlog.contextvars.clear_contextvars()
