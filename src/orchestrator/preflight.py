"""Preflight checks before orchestrator jobs run."""

from __future__ import annotations

import subprocess
import time
from typing import Callable

import requests

from src.openstat.utils.bypass import _flaresolverr_api_url, get_flaresolverr_url
from src.services.config import PROJECT_ROOT

LogFn = Callable[[str], None]


def is_flaresolverr_healthy(timeout: float = 10.0) -> bool:
    """Return True if FlareSolverr responds to sessions.create."""
    api_url = _flaresolverr_api_url()
    try:
        response = requests.post(
            api_url,
            json={"cmd": "sessions.create"},
            timeout=timeout,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return False
    return data.get("status") == "ok"


def _start_flaresolverr_compose(log: LogFn) -> bool:
    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "flaresolverr"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log(f"docker compose failed: {exc}")
        return False

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        log(f"docker compose up -d flaresolverr failed (exit {result.returncode}): {err}")
        return False
    return True


def ensure_flaresolverr(
    *,
    start_if_down: bool = True,
    wait_seconds: float = 60.0,
    poll_interval: float = 3.0,
    log: LogFn | None = None,
) -> bool:
    """
    Ensure FlareSolverr is reachable before OpenSTAT runs.

    Optionally starts the docker compose service and polls until healthy.
    """
    if log is None:
        log = print

    base = get_flaresolverr_url()
    log(f"FlareSolverr preflight: checking {base}")

    if is_flaresolverr_healthy():
        log("FlareSolverr is healthy.")
        return True

    if not start_if_down:
        log("FlareSolverr is not reachable and start_if_down=False.")
        return False

    log("FlareSolverr down — starting docker compose service flaresolverr...")
    if not _start_flaresolverr_compose(log):
        log(
            "Could not start FlareSolverr. Run manually: "
            f"docker compose up -d flaresolverr (from {PROJECT_ROOT})"
        )
        return False

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if is_flaresolverr_healthy():
            log("FlareSolverr is healthy after compose start.")
            return True
        time.sleep(poll_interval)

    log(
        f"FlareSolverr still unreachable after {wait_seconds:.0f}s. "
        f"Check FLARESOLVERR_URL and docker compose logs flaresolverr."
    )
    return False


def _qdrant_health_url() -> str:
    from src.api.settings import get_settings

    base = get_settings().qdrant_url.rstrip("/")
    return f"{base}/healthz"


def is_qdrant_healthy(timeout: float = 5.0) -> bool:
    """Return True if Qdrant responds to /healthz."""
    try:
        response = requests.get(_qdrant_health_url(), timeout=timeout)
        return response.status_code == 200
    except requests.RequestException:
        return False


def ensure_qdrant(
    *,
    start_if_down: bool = True,
    wait_seconds: float = 60.0,
    poll_interval: float = 3.0,
    log: LogFn | None = None,
) -> bool:
    """Ensure external Qdrant is reachable before indexing runs."""
    if log is None:
        log = print

    url = _qdrant_health_url()
    log(f"Qdrant preflight: checking {url}")

    if is_qdrant_healthy():
        log("Qdrant is healthy.")
        return True

    log(
        "Qdrant is not reachable. Qdrant is external to this compose stack; "
        "start or fix the separate Qdrant deployment and set QDRANT_URL "
        "(or DOCKER_QDRANT_URL when running through docker compose)."
    )
    return False
