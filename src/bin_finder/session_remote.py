"""F016 read-only verification of existing F012 local cache provenance.

The signed rendition URL is intentionally not persisted. This check uses
F012's application-controlled cache trust boundary and is not a license grant.
"""
from __future__ import annotations

import re
from pathlib import Path

from bin_finder.acquisition.service import FORMAT as F012_FORMAT, default_cache_root
from bin_finder.session_store import SessionStoreError, _read


def verified_remote_session_media(row, media: Path) -> bool:
    if row["provider"] not in {"pexels", "pixabay"}:
        return False
    root = default_cache_root()
    if (not root.is_absolute() or media.name != "media.mp4"
            or media.parent.parent != root
            or not re.fullmatch(r"[0-9a-f]{64}", media.parent.name)):
        return False
    manifest = media.parent / "manifest.json"
    try:
        if not manifest.is_file() or manifest.stat().st_size > 128 * 1024:
            return False
        data = _read(manifest)  # Reject linked paths and duplicate JSON keys.
        rendition = data.get("selected_rendition")
        size = media.stat().st_size
        limit = data.get("byte_limit")
        rendition_hash = data.get("rendition_identifier")
        return bool(
            data.get("format") == F012_FORMAT
            and type(data.get("cache_version")) is int
            and data["cache_version"] == 1
            and data.get("cache_key") == media.parent.name
            and data.get("provider") == row["provider"]
            and data.get("source_id") == row["source_id"]
            and row["source_id"].startswith(row["provider"] + ":")
            and data.get("usage_authorization") == "user_authorized_acquisition"
            and data.get("local_path") == str(media)
            and data.get("sha256") == row["source_metadata"]["media_sha256"]
            and type(data.get("size_bytes")) is int
            and data["size_bytes"] == size
            and type(limit) is int and 0 < size <= limit
            and isinstance(rendition_hash, str)
            and re.fullmatch(r"[0-9a-f]{64}", rendition_hash)
            and isinstance(rendition, dict)
            and rendition.get("identifier") == rendition_hash
            and all(type(rendition.get(k)) is int and rendition[k] >= 0
                    for k in ("width", "height"))
        )
    except (SessionStoreError, OSError, TypeError, ValueError, KeyError):
        return False
