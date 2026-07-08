"""
Cloudflare bypass using FlareSolverr (Docker).
Set FLARESOLVERR_URL in .env (e.g. http://localhost:8191).
"""
import os
import requests
from urllib.parse import urlparse

from src.utils.url_policy import UrlPolicyError, validate_http_url


def get_flaresolverr_url():
    url = (os.getenv("FLARESOLVERR_URL") or "http://localhost:8191").strip().rstrip("/")
    return url


def _flaresolverr_api_url():
    base = get_flaresolverr_url().rstrip("/")
    return base if base.endswith("/v1") else f"{base}/v1"


def _request_flaresolverr(base, payload, log, timeout=70):
    api_url = _flaresolverr_api_url()
    try:
        r = requests.post(api_url, json=payload, timeout=timeout, headers={"Content-Type": "application/json"})
        r.raise_for_status()
        return r.json(), None
    except requests.RequestException as e:
        return None, str(e)
    except ValueError as e:
        return None, f"Invalid JSON: {e}"


def get_cloudflare_cookies(url, log=None):
    """Call FlareSolverr to solve Cloudflare for the given URL. Returns (cookies_list, user_agent)."""
    if log is None:
        log = print
    try:
        validate_http_url(url)
    except UrlPolicyError as exc:
        log(f"FlareSolverr URL rejected by policy: {exc}")
        return [], None
    base = get_flaresolverr_url()
    session_id = None
    create_payload = {"cmd": "sessions.create"}
    data, err = _request_flaresolverr(base, create_payload, log, timeout=90)
    if err:
        log(f"FlareSolverr sessions.create failed: {err}")
        data, err = _request_flaresolverr(base, {"cmd": "request.get", "url": url, "maxTimeout": 60000}, log, timeout=70)
        if err:
            log(f"FlareSolverr request.get failed: {err}")
            return [], None
        session_id = None
    else:
        if data.get("status") != "ok":
            log(f"FlareSolverr sessions.create: {data.get('message', 'Unknown error')}")
            return [], None
        session_id = (data.get("solution") or {}).get("session")
        if not session_id:
            data, err = _request_flaresolverr(base, {"cmd": "request.get", "url": url, "maxTimeout": 60000}, log, timeout=70)
            if err:
                return [], None
        else:
            payload = {"cmd": "request.get", "url": url, "maxTimeout": 60000, "session": session_id}
            data, err = _request_flaresolverr(base, payload, log, timeout=70)
            if err:
                try:
                    requests.post(_flaresolverr_api_url(), json={"cmd": "sessions.destroy", "session": session_id}, timeout=5)
                except Exception:
                    pass
                return [], None
            try:
                requests.post(_flaresolverr_api_url(), json={"cmd": "sessions.destroy", "session": session_id}, timeout=5)
            except Exception:
                pass
    if data.get("status") != "ok":
        log(f"FlareSolverr: {data.get('message', 'Unknown error')}")
        return [], None
    solution = data.get("solution") or {}
    cookies_raw = solution.get("cookies") or solution.get("cookie") or []
    if not isinstance(cookies_raw, list):
        cookies_raw = []
    user_agent = solution.get("userAgent") or solution.get("User-Agent")
    parsed = urlparse(url)
    scheme, netloc = parsed.scheme or "https", parsed.netloc or ""
    cookie_base_url = f"{scheme}://{netloc}/" if netloc else ""
    cookies = []
    for c in cookies_raw:
        if not isinstance(c, dict) or c.get("name") is None or not cookie_base_url:
            continue
        cookies.append({
            "name": c["name"],
            "value": str(c.get("value") or ""),
            "url": cookie_base_url,
        })
    if cookies:
        log(f"FlareSolverr: got {len(cookies)} cookie(s).")
    return cookies, user_agent
