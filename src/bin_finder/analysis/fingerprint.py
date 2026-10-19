from __future__ import annotations

import hashlib
from pathlib import Path

from bin_finder.analysis.models import MediaFingerprint


def fingerprint_file(path: str | Path, chunk_size: int = 1024 * 1024) -> MediaFingerprint:
    media_path = Path(path)
    stat = media_path.stat()
    digest = hashlib.sha256()
    with media_path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return MediaFingerprint(
        sha256=digest.hexdigest(),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
    )
