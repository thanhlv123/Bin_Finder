"""Defensive primitives for untrusted video-search payloads."""
from __future__ import annotations

import math
from urllib.parse import urlsplit

from bin_finder.providers.base import ProviderError


def number(value: object) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def text(value: object) -> str:
    return value if isinstance(value, str) else ""


def url(value: object) -> str:
    value = text(value)
    try:
        parsed = urlsplit(value)
        return value if parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.username else ""
    except ValueError:
        return ""


def records(payload: object, key: str, provider: str) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise ProviderError(f"{provider}: invalid search response")
    return [item for item in payload[key] if isinstance(item, dict)]


def asset_id(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return str(value)
    if isinstance(value, str) and value.isascii() and value.isdigit() and value.strip("0"):
        return value
    return ""
