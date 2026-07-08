"""API-key authentication with public/admin scopes.

Keys are read from environment variables (`API_KEYS_PUBLIC`, `API_KEYS_ADMIN`)
and never logged in raw form — log fields use a short SHA-256 prefix instead.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, cast

import jwt
from fastapi import Depends, Header

from src.api.errors import ApiError, ErrorCode
from src.api.settings import Settings, get_settings

API_KEY_HEADER = "X-API-Key"
AUTHORIZATION_HEADER = "Authorization"
SettingsDep = Annotated[Settings, Depends(get_settings)]
ApiKeyHeader = Annotated[str | None, Header(alias=API_KEY_HEADER)]
AuthorizationHeader = Annotated[str | None, Header(alias=AUTHORIZATION_HEADER)]


class AuthScope(StrEnum):
    PUBLIC = "public"
    ADMIN = "admin"


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    role: str | None = None
    tenant_id: str | None = None
    scopes: tuple[str, ...] = ()


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
        settings: SettingsDep,
        api_key: ApiKeyHeader = None,
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


def _split_scopes(claims: dict[str, Any]) -> tuple[str, ...]:
    raw_scopes = claims.get("scopes")
    if isinstance(raw_scopes, list):
        return tuple(str(scope).strip() for scope in raw_scopes if str(scope).strip())

    raw_scope = claims.get("scope")
    if isinstance(raw_scope, str):
        return tuple(scope for scope in raw_scope.split() if scope)

    return ()


def _string_claim(claims: dict[str, Any], name: str) -> str | None:
    value = claims.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError(
            ErrorCode.UNAUTHORIZED,
            "Invalid Authorization header",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


def _jwt_decode_options(settings: Settings) -> dict[str, Any]:
    options: dict[str, Any] = {"require": ["sub", "exp"]}
    if not settings.jwt_audience:
        options["verify_aud"] = False
    if not settings.jwt_issuer:
        options["verify_iss"] = False
    return options


def _decode_current_user(token: str, settings: Settings) -> CurrentUser:
    if not settings.jwt_secret:
        raise ApiError(
            ErrorCode.INTERNAL_ERROR,
            "JWT auth is enabled but JWT_SECRET is not configured",
            status_code=500,
        )

    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience or None,
            issuer=settings.jwt_issuer or None,
            options=cast(Any, _jwt_decode_options(settings)),
        )
    except jwt.PyJWTError as exc:
        raise ApiError(
            ErrorCode.UNAUTHORIZED,
            "Invalid or expired JWT",
            status_code=401,
            details={"type": exc.__class__.__name__},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if not isinstance(claims, dict):
        raise ApiError(
            ErrorCode.UNAUTHORIZED,
            "Invalid JWT claims",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = _string_claim(claims, "sub")
    if user_id is None:
        raise ApiError(
            ErrorCode.UNAUTHORIZED,
            "JWT subject is required",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUser(
        user_id=user_id,
        role=_string_claim(claims, "role"),
        tenant_id=_string_claim(claims, "tenant_id") or _string_claim(claims, "org_id"),
        scopes=_split_scopes(claims),
    )


def get_current_user_optional(
    settings: SettingsDep,
    authorization: AuthorizationHeader = None,
) -> CurrentUser | None:
    if not settings.jwt_auth_enabled:
        return None

    token = _bearer_token(authorization)
    if token is None:
        if settings.jwt_required_for_agent:
            raise ApiError(
                ErrorCode.UNAUTHORIZED,
                "JWT bearer token required",
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return None

    return _decode_current_user(token, settings)


def get_current_user_required(
    settings: SettingsDep,
    authorization: AuthorizationHeader = None,
) -> CurrentUser:
    token = _bearer_token(authorization)
    if token is None:
        raise ApiError(
            ErrorCode.UNAUTHORIZED,
            "JWT bearer token required",
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode_current_user(token, settings)


require_public = _require_scope(AuthScope.PUBLIC)
require_admin = _require_scope(AuthScope.ADMIN)


def require_agent(
    settings: SettingsDep,
    api_key: ApiKeyHeader = None,
) -> AuthScope:
    """Agent route: admin keys, dedicated agent keys, or public if explicitly allowed."""
    scope = _resolve_scope(api_key, settings)
    if scope is None:
        raise ApiError(
            ErrorCode.UNAUTHORIZED,
            "Missing or invalid API key",
            status_code=401,
            headers={"WWW-Authenticate": API_KEY_HEADER},
        )
    if scope is AuthScope.ADMIN:
        return scope
    if api_key and api_key in settings.agent_keys:
        return scope
    if settings.agent_allow_public and scope is AuthScope.PUBLIC:
        return scope
    raise ApiError(
        ErrorCode.FORBIDDEN,
        "Agent scope required (admin or agent API key)",
        status_code=403,
    )
