import re
from urllib.parse import urlparse


def safe_id_from_url(url: str, max_len: int = 120, fallback: str = "doc") -> str:
    try:
        parsed = urlparse(url)
        path = (parsed.path or "").strip("/") or fallback
    except Exception:
        path = fallback
    stem = re.sub(r"[^\w\-.]", "_", path)[:max_len] or fallback
    return stem
