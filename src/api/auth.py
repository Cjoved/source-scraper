"""API-key authentication with public/admin scopes.

Keys are read from environment variables (`API_KEYS_PUBLIC`, `API_KEYS_ADMIN`)
and never logged in raw form — log fields use a short SHA-256 prefix instead.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum

from fastapi import Depends, Header

from src.api.errors import ApiError, ErrorCode
from src.api.settings import Settings, get_settings

API_KEY_HEADER = "X-API-Key"


class AuthScope(StrEnum):
    PUBLIC = "public"
    ADMIN = "admin"


def hash_key(raw_key: str) -> str:
    """Return a short, log-safe digest of an API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:12]


def _resolve_scope(api_key: str | None, settings: Settings) -> AuthScope | None:
    if settings.api_auth_disabled:
        return AuthScope.ADMIN
    if not api_key:
        return None
    if api_key in settings.admin_keys:
        return AuthScope.ADMIN
    if api_key in settings.public_keys:
        return AuthScope.PUBLIC
    return None


def _require_scope(required: AuthScope):
    def dependency(
        api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
        settings: Settings = Depends(get_settings),
    ) -> AuthScope:
        scope = _resolve_scope(api_key, settings)
        if scope is None:
            raise ApiError(
                ErrorCode.UNAUTHORIZED,
                "Missing or invalid API key",
                status_code=401,
                headers={"WWW-Authenticate": API_KEY_HEADER},
            )
        if required is AuthScope.ADMIN and scope is not AuthScope.ADMIN:
            raise ApiError(
                ErrorCode.FORBIDDEN,
                "Admin scope required",
                status_code=403,
            )
        return scope

    return dependency


require_public = _require_scope(AuthScope.PUBLIC)
require_admin = _require_scope(AuthScope.ADMIN)
