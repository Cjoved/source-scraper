"""Uniform API error contract.

Every route returns errors in the same envelope:

```json
{
  "error": {
    "code": "INVALID_FILTER",
    "message": "...",
    "details": {...}
  }
}
```

Errors are raised as :class:`ApiError` and translated into JSON responses by the
handler installed in :mod:`src.api.app`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_FILTER = "INVALID_FILTER"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    QDRANT_UNAVAILABLE = "QDRANT_UNAVAILABLE"
    COLLECTION_NOT_FOUND = "COLLECTION_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ApiError(Exception):
    """Domain-level error that maps cleanly to an HTTP response."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.headers = headers or {}


def error_payload(code: ErrorCode, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code.value, "message": message, "details": details or {}}}


async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.code, exc.message, exc.details),
        headers=exc.headers,
    )


async def validation_error_handler(
    _request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_payload(
            ErrorCode.VALIDATION_ERROR,
            "Request validation failed",
            {"errors": exc.errors()},
        ),
    )


async def unexpected_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=error_payload(
            ErrorCode.INTERNAL_ERROR,
            "An unexpected error occurred",
            {"type": exc.__class__.__name__},
        ),
    )
