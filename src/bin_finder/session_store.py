"""F016 atomic user-local snapshot storage."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from bin_finder.session_codec import FORMAT, validate_snapshot

MAX_BYTES = 2 * 1024 * 1024


class SessionStoreError(ValueError):
    pass


def default_root():
    base = os.environ.get("LOCALAPPDATA", "").strip()
    return (Path(base) / "BinFinder" / "sessions" if base
            else Path.home() / ".bin_finder" / "sessions")


def _check(path):
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise SessionStoreError("linked-path-refused")


def _read(path):
    _check(path)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise SessionStoreError("missing-or-large")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SessionStoreError("duplicate-key")
            result[key] = value
        return result
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise SessionStoreError("too-large")
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (OSError, UnicodeError, ValueError):
        raise SessionStoreError("invalid-json") from None


def _write(path, payload):
    data = json.dumps(payload, sort_keys=True, ensure_ascii=True,
                      allow_nan=False).encode("utf-8")
    if len(data) > MAX_BYTES:
        raise SessionStoreError("too-large")
    _check(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _check(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".tmp",
                                         dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class SessionStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else default_root()

    def path(self, project_id):
        digest = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
        return self.root / (digest + ".json")

    def save(self, payload):
        payload = validate_snapshot(payload)
        project_id = payload["project_id"]
        target = self.path(project_id)
        _write(target, payload)
        _write(self.root / "active.json", {"format": FORMAT, "project_id": project_id})
        return target

    def load(self, project_id):
        payload = validate_snapshot(_read(self.path(project_id)))
        if payload["project_id"] != project_id:
            raise SessionStoreError("wrong-project")
        return payload

    def load_active(self):
        marker = self.root / "active.json"
        if not marker.exists():
            return None
        pointer = _read(marker)
        if (not isinstance(pointer, dict) or
                set(pointer) != {"format", "project_id"} or
                pointer["format"] != FORMAT or
                not isinstance(pointer["project_id"], str)):
            raise SessionStoreError("invalid-pointer")
        return self.load(pointer["project_id"])
