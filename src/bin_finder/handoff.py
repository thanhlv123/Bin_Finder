"""F017 portable handoff package: builder and read-only verifier. No Qt, network or FFmpeg.

The handoff describes an already exported F015 library with package-relative paths only.
It never re-evaluates F010 on materialized coordinates; READY on original source
coordinates stays authoritative and is only echoed here.
"""
from __future__ import annotations

import errno
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from bin_finder.analysis.fingerprint import fingerprint_file

FORMAT = "bin_finder_handoff_v1"
HANDOFF_FILENAME = "_bin_finder_handoff.json"
PRODUCER = "Bin Finder"
# Mirrors bin_finder.final_export.FORMAT / manifest name (kept literal to avoid a cycle).
MANIFEST_FORMAT = "bin_finder_final_export_v1"
MANIFEST_FILENAME = "footage_manifest.json"

MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_PATH_WINDOWS = 260
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FOOTAGE_NAME = re.compile(r"[A-Za-z0-9_-]{1,100}\.mp4")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"{p}{n}" for p in ("COM", "LPT") for n in range(1, 10))}
PROVENANCE_KEYS = ("license_basis", "license_url", "creator_url", "usage_authorization",
                   "asset_id", "creator_id")
_URL_KEYS = ("source_url", "license_url", "creator_url")

TOP_KEYS = {"format", "producer", "project_id", "ready", "scene_count", "clip_count",
            "total_duration_seconds", "manifest_relative_path", "manifest_sha256", "scenes"}
SCENE_KEYS = {"scene_id", "scene_order", "script_text", "vietnamese_text",
              "target_duration_seconds", "footage"}
FOOTAGE_KEYS = {"clip_id", "relative_path", "exported_file_sha256", "byte_count",
                "duration_seconds", "provider", "source_id", "semantic_score", "vlm_score",
                "final_score", "rights_status", "creator", "original_source_start_seconds",
                "original_source_end_seconds", "original_source_media_sha256"}
OPTIONAL_FOOTAGE_KEYS = {"source_url", "provenance"}


class HandoffError(Exception):
    """Fail-closed handoff problem; ``code`` is a short stable identifier."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class HandoffReport:
    project_id: str
    scene_count: int
    clip_count: int
    total_duration_seconds: float
    clip_paths: tuple[Path, ...]


def _redact(value: object) -> str:
    text = value if isinstance(value, str) else ""
    for name, secret in os.environ.items():
        if name.startswith("BIN_FINDER_") and ("KEY" in name or "SECRET" in name) and secret:
            text = text.replace(secret, "[redacted]")
    return text


def _number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _score(value: object) -> bool:
    return _number(value) and 0 <= value <= 1


def _text(value: object) -> bool:
    return isinstance(value, str)


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _hex(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def validate_relative_path(value: object) -> PurePosixPath:
    """Accept only ``footage/<name>.mp4`` written with forward slashes."""
    if not isinstance(value, str) or not value:
        raise HandoffError("path-invalid")
    if value.startswith(("/", "\\")) or "\\" in value or ":" in value or "\x00" in value:
        raise HandoffError("path-absolute-or-unsafe")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise HandoffError("path-traversal")
    if len(parts) != 2 or parts[0] != "footage" or not _FOOTAGE_NAME.fullmatch(parts[1]):
        raise HandoffError("path-unexpected-layout")
    if parts[1][:-4].upper() in _RESERVED:
        raise HandoffError("path-reserved-name")
    return PurePosixPath(value)


def build_handoff(project_id, scenes, rows, stage, *, include_metadata=True):
    """Write ``_bin_finder_handoff.json`` into a private staging directory.

    ``scenes`` are the script-ordered F014 SceneRecords, ``rows`` the F015 manifest
    rows for those scenes. Everything is derived from already-validated F015 data.
    """
    stage = Path(stage)
    by_scene = {row["scene_id"]: row for row in rows}
    manifest = stage / MANIFEST_FILENAME
    entries = []
    for scene in scenes:
        row = by_scene.get(scene.scene_id)
        if row is None:
            raise ValueError("handoff-scene-missing")
        relative = validate_relative_path(row["exported_path"])
        file = stage / relative.as_posix()
        footage = {
            "clip_id": row["clip_id"], "relative_path": relative.as_posix(),
            "exported_file_sha256": row["exported_file_sha256"],
            "byte_count": file.stat().st_size, "duration_seconds": row["duration"],
            "provider": row["provider"], "source_id": row["source_id"],
            "semantic_score": row["semantic_score"], "vlm_score": row["vlm_score"],
            "final_score": row["final_score"], "rights_status": row["rights_status"],
            "creator": row["creator"],
            "original_source_start_seconds": row["original_source_start_seconds"],
            "original_source_end_seconds": row["original_source_end_seconds"],
            "original_source_media_sha256": row["original_source_media_sha256"],
        }
        if include_metadata:
            metadata = row.get("source_metadata") or {}
            provenance = {key: metadata[key] for key in PROVENANCE_KEYS if key in metadata}
            if provenance:
                footage["provenance"] = provenance
            if row.get("source_url"):
                footage["source_url"] = row["source_url"]
        entries.append({
            "scene_id": scene.scene_id, "scene_order": scene.order,
            "script_text": _redact(scene.english_text),
            "vietnamese_text": _redact(scene.vietnamese_text),
            "target_duration_seconds": scene.target_duration, "footage": footage})
    payload = {
        "format": FORMAT, "producer": PRODUCER, "project_id": _redact(project_id),
        "ready": True, "scene_count": len(entries), "clip_count": len(entries),
        "total_duration_seconds": sum(e["footage"]["duration_seconds"] for e in entries),
        "manifest_relative_path": MANIFEST_FILENAME,
        "manifest_sha256": fingerprint_file(manifest).sha256, "scenes": entries}
    target = stage / HANDOFF_FILENAME
    temporary = stage / (HANDOFF_FILENAME + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
                         encoding="utf-8")
    os.replace(temporary, target)
    return target


def _no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HandoffError("json-duplicate-key")
        result[key] = value
    return result


def _reject_constant(_name):
    raise HandoffError("json-nonfinite")


def _is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _lstat(path: Path):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        raise HandoffError("file-missing") from None
    except OSError as error:
        too_long = (getattr(error, "winerror", None) == 206 or error.errno == errno.ENAMETOOLONG
                    or (os.name == "nt" and len(str(path)) >= MAX_PATH_WINDOWS))
        raise HandoffError("path-too-long" if too_long else "file-unreadable") from None


def _read_json(path: Path, missing: str, malformed: str):
    try:
        info = _lstat(path)
    except HandoffError as error:
        raise HandoffError(missing if error.code == "file-missing" else error.code) from None
    if not stat.S_ISREG(info.st_mode) or _is_link(path):
        raise HandoffError(missing)
    if info.st_size > MAX_JSON_BYTES:
        raise HandoffError("json-too-large")
    try:
        data = json.loads(path.read_bytes().decode("utf-8"), object_pairs_hook=_no_duplicates,
                          parse_constant=_reject_constant)
    except HandoffError:
        raise
    except (OSError, ValueError, RecursionError):
        raise HandoffError(malformed) from None
    if not isinstance(data, dict):
        raise HandoffError(malformed)
    return data


def _check_file(root: Path, relative: PurePosixPath) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        if _is_link(current):
            raise HandoffError("path-linked")
    info = _lstat(current)
    if not stat.S_ISREG(info.st_mode):
        raise HandoffError("file-not-regular")
    if info.st_size == 0:
        raise HandoffError("file-empty")
    return current


def _check_url(value: object) -> None:
    if not isinstance(value, str) or "?" in value or "#" in value:
        raise HandoffError("provenance-unsafe-url")


def verify_handoff_package(package: str | os.PathLike) -> HandoffReport:
    """Read-only verification. Raises ``HandoffError`` on the first problem; never repairs."""
    root = Path(package)
    try:
        if _is_link(root):
            raise HandoffError("package-linked")
        if not stat.S_ISDIR(_lstat(root).st_mode):
            raise HandoffError("package-not-directory")
    except HandoffError as error:
        raise HandoffError("package-missing" if error.code == "file-missing" else error.code) from None
    data = _read_json(root / HANDOFF_FILENAME, "handoff-missing", "json-malformed")

    if data.get("format") != FORMAT:
        raise HandoffError("format-unsupported")
    if set(data) != TOP_KEYS:
        raise HandoffError("schema-keys")
    if data["producer"] != PRODUCER or not _nonempty(data["project_id"]):
        raise HandoffError("schema-identity")
    if data["ready"] is not True:
        raise HandoffError("not-ready")
    scenes = data["scenes"]
    if not isinstance(scenes, list) or not scenes:
        raise HandoffError("no-scenes")
    counts = (data["scene_count"], data["clip_count"])
    if any(type(c) is not int for c in counts) or counts != (len(scenes), len(scenes)):
        raise HandoffError("count-mismatch")
    if not _number(data["total_duration_seconds"]):
        raise HandoffError("duration-invalid")
    if data["manifest_relative_path"] != MANIFEST_FILENAME or not _hex(data["manifest_sha256"]):
        raise HandoffError("manifest-reference-invalid")

    manifest_path = root / MANIFEST_FILENAME
    manifest = _read_json(manifest_path, "manifest-missing", "manifest-malformed")
    if fingerprint_file(manifest_path).sha256 != data["manifest_sha256"]:
        raise HandoffError("manifest-inconsistent")
    rows = manifest.get("clips")
    if (manifest.get("format") != MANIFEST_FORMAT or manifest.get("project_id") != data["project_id"]
            or not isinstance(manifest.get("readiness"), dict)
            or manifest["readiness"].get("ready") is not True
            or not isinstance(rows, list) or len(rows) != len(scenes)
            or manifest.get("scene_count") != len(scenes)
            or manifest.get("selected_count") != len(scenes)
            or manifest.get("exported_count") != len(scenes)):
        raise HandoffError("manifest-inconsistent")

    seen_scenes, seen_clips, seen_paths = set(), set(), set()
    previous_order, total, clip_paths = 0, 0.0, []
    for scene, row in zip(scenes, rows):
        if not isinstance(scene, dict) or set(scene) != SCENE_KEYS:
            raise HandoffError("schema-keys")
        footage = scene["footage"]
        if not isinstance(footage, dict):
            raise HandoffError("footage-missing")
        keys = set(footage)
        if not FOOTAGE_KEYS <= keys or not keys <= FOOTAGE_KEYS | OPTIONAL_FOOTAGE_KEYS:
            raise HandoffError("schema-keys")
        if not isinstance(row, dict):
            raise HandoffError("manifest-inconsistent")
        scene_id, order = scene["scene_id"], scene["scene_order"]
        if not _nonempty(scene_id) or type(order) is not int or order < 1:
            raise HandoffError("scene-invalid")
        if scene_id in seen_scenes:
            raise HandoffError("scene-duplicate")
        if order <= previous_order:
            raise HandoffError("scene-order-invalid")
        seen_scenes.add(scene_id)
        previous_order = order
        if not (_text(scene["script_text"]) and _text(scene["vietnamese_text"])
                and _number(scene["target_duration_seconds"])
                and scene["target_duration_seconds"] >= 0):
            raise HandoffError("scene-invalid")
        clip_id = footage["clip_id"]
        if not _nonempty(clip_id):
            raise HandoffError("clip-invalid")
        if clip_id in seen_clips:
            raise HandoffError("clip-duplicate")
        seen_clips.add(clip_id)
        relative = validate_relative_path(footage["relative_path"])
        if relative.as_posix().casefold() in seen_paths:
            raise HandoffError("path-duplicate")
        seen_paths.add(relative.as_posix().casefold())
        duration = footage["duration_seconds"]
        if not _number(duration) or duration <= 0:
            raise HandoffError("duration-invalid")
        if not all(_score(footage[k]) for k in ("semantic_score", "vlm_score", "final_score")):
            raise HandoffError("score-invalid")
        start, end = footage["original_source_start_seconds"], footage["original_source_end_seconds"]
        if (not _number(start) or not _number(end) or start < 0 or end <= start
                or not math.isclose(end - start, duration, abs_tol=1e-6)):
            raise HandoffError("range-invalid")
        if not (_hex(footage["exported_file_sha256"]) and _hex(footage["original_source_media_sha256"])):
            raise HandoffError("sha256-invalid")
        count = footage["byte_count"]
        if type(count) is not int or count <= 0:
            raise HandoffError("byte-count-invalid")
        if not all(_text(footage[k]) for k in ("provider", "source_id", "rights_status", "creator")):
            raise HandoffError("provenance-invalid")
        if not _nonempty(footage["provider"]) or not _nonempty(footage["rights_status"]):
            raise HandoffError("provenance-invalid")
        if "source_url" in footage and footage["source_url"]:
            _check_url(footage["source_url"])
        if "provenance" in footage:
            provenance = footage["provenance"]
            if (not isinstance(provenance, dict) or not set(provenance) <= set(PROVENANCE_KEYS)
                    or not all(_text(v) for v in provenance.values())):
                raise HandoffError("provenance-invalid")
            for key in _URL_KEYS:
                if provenance.get(key):
                    _check_url(provenance[key])

        # Identity must agree with the F015 manifest row for the same position.
        if (row.get("scene_id") != scene_id or row.get("scene_order") != order):
            raise HandoffError("scene-identity-mismatch")
        if row.get("clip_id") != clip_id:
            raise HandoffError("clip-identity-mismatch")
        if row.get("exported_path") != relative.as_posix() or row.get("filename") != relative.name:
            raise HandoffError("exported-path-mismatch")
        for key, field in (("provider", "provider"), ("source_id", "source_id"),
                           ("rights_status", "rights_status"), ("creator", "creator")):
            if row.get(key) != footage[field]:
                raise HandoffError("provenance-mismatch")
        for key in ("semantic_score", "vlm_score", "final_score", "original_source_start_seconds",
                    "original_source_end_seconds"):
            if row.get(key) != footage[key]:
                raise HandoffError("manifest-inconsistent")
        if (row.get("duration") != duration
                or row.get("exported_file_sha256") != footage["exported_file_sha256"]
                or row.get("original_source_media_sha256") != footage["original_source_media_sha256"]):
            raise HandoffError("manifest-inconsistent")

        path = _check_file(root, relative)
        if os.lstat(path).st_size != count:
            raise HandoffError("byte-count-mismatch")
        try:
            actual = fingerprint_file(path).sha256
        except OSError:
            raise HandoffError("file-unreadable") from None
        if actual != footage["exported_file_sha256"]:
            raise HandoffError("sha256-mismatch")
        total += duration
        clip_paths.append(path)

    if not math.isclose(total, data["total_duration_seconds"], abs_tol=1e-6):
        raise HandoffError("duration-invalid")
    return HandoffReport(data["project_id"], len(scenes), len(scenes), total, tuple(clip_paths))
