"""Shared text utilities: re-exports from canonical src.utils modules."""

from src.utils.text_chunk import chunk_text
from src.utils.url_id import safe_id_from_url

__all__ = ["chunk_text", "safe_id_from_url"]
