"""Per-endpoint rate limiting via slowapi.

The limiter keys requests on `X-API-Key` (falling back to the remote address)
so anonymous abuse is still bounded.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.auth import API_KEY_HEADER, hash_key
from src.api.errors import ErrorCode, error_payload


def _key_func(request: Request) -> str:
    api_key = request.headers.get(API_KEY_HEADER)
    if api_key:
        return f"key:{hash_key(api_key)}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=_key_func, default_limits=[])


def rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content=error_payload(
            ErrorCode.RATE_LIMITED,
            "Too many requests",
            {"limit": str(exc.detail)},
        ),
        headers={"Retry-After": "60"},
    )
