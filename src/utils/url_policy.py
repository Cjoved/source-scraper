"""HTTP URL validation for scraper and FlareSolverr targets."""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

DEFAULT_ALLOWED_HOST_SUFFIXES: tuple[str, ...] = (
    "prism.philrice.gov.ph",
    "openstat.psa.gov.ph",
    "philrice.gov.ph",
    "www.philrice.gov.ph",
    "pinoyrice.com",
    "www.pinoyrice.com",
    "irri.org",
    "www.irri.org",
)


class UrlPolicyError(ValueError):
    """Raised when a URL fails outbound fetch policy checks."""


def allow_private_targets() -> bool:
    raw = os.getenv("URL_ALLOW_PRIVATE_TARGETS", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _host_allowed(host: str, allowed_suffixes: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    if not host:
        return False
    for suffix in allowed_suffixes:
        suffix = suffix.lower()
        if host == suffix or host.endswith(f".{suffix}"):
            return True
    return False


def _is_private_or_reserved_host(host: str) -> bool:
    host = host.strip().lower()
    if host in {"localhost", "localhost.localdomain"}:
        return True
    if host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in addr_infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            return True
    return False


def validate_http_url(
    url: str,
    *,
    allowed_host_suffixes: tuple[str, ...] | None = None,
    allow_private: bool | None = None,
) -> str:
    """Validate URL scheme/host before outbound fetch. Returns normalized URL."""
    raw = (url or "").strip()
    if not raw:
        raise UrlPolicyError("URL is empty")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise UrlPolicyError(f"Unsupported URL scheme: {scheme or '(none)'}")

    host = (parsed.netloc or "").split("@")[-1].split(":")[0].strip()
    if not host:
        raise UrlPolicyError("URL host is missing")

    private_ok = allow_private_targets() if allow_private is None else allow_private
    if not private_ok and _is_private_or_reserved_host(host):
        raise UrlPolicyError(f"Private or reserved host not allowed: {host}")

    suffixes = allowed_host_suffixes or DEFAULT_ALLOWED_HOST_SUFFIXES
    if not _host_allowed(host, suffixes):
        raise UrlPolicyError(f"Host not in allowlist: {host}")

    return raw
