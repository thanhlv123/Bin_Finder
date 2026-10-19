from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.analysis.probe import FFprobeMediaProbe
from bin_finder.evaluation import ReviewDecision
from bin_finder.models import CandidateRecord
from bin_finder.acquisition.transport import StreamingTransport, validate_url

FORMAT = "bin_finder_acquisition_v1"
DEFAULT_MAX_BYTES = 1024 * 1024 * 1024  # 1 GiB per asset, not an aggregate quota.


class AcquisitionError(RuntimeError):
    pass


class AcquisitionCancelled(AcquisitionError):
    pass


@dataclass(frozen=True)
class AcquisitionRequest:
    candidate: CandidateRecord
    review: ReviewDecision
    user_authorized: bool = False


@dataclass(frozen=True)
class AcquisitionResult:
    candidate: CandidateRecord
    local_path: Path
    manifest_path: Path
    size_bytes: int
    sha256: str
    cache_hit: bool


def default_cache_root() -> Path:
    base = os.environ.get("LOCALAPPDATA", "").strip()
    return (Path(base) / "BinFinder" / "cache" / "media" if base else
            Path.home() / ".bin_finder" / "cache" / "media")


def cache_key(candidate: CandidateRecord) -> str:
    return hashlib.sha256(json.dumps(
        [FORMAT, candidate.provider, candidate.source_id, candidate.preview_url],
        separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _safe_text(value: object) -> str:
    text = value if isinstance(value, str) else ""
    for name, secret in os.environ.items():
        if name.startswith("BIN_FINDER_") and ("KEY" in name or "SECRET" in name) and secret:
            text = text.replace(secret, "[redacted]")
    return text[:2048]


def _safe_url(value: object) -> str:
    try:
        parsed = urlsplit(validate_url(value))
        # Queries/fragments may carry signed credentials; persist neither.
        return _safe_text(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")))
    except (ValueError, TypeError):
        return ""


def _provenance(candidate: CandidateRecord) -> dict:
    metadata = candidate.source_metadata
    # Intentionally do not recursively persist arbitrary provider metadata.
    safe = {key: _safe_text(metadata.get(key)) for key in
            ("asset_id", "creator_id", "license_basis", "rendition") if key in metadata}
    for key in ("creator_url", "license_url"):
        if key in metadata:
            safe[key] = _safe_url(metadata[key])
    if metadata.get("usage_authorization") in {"unknown", "user_authorized_acquisition"}:
        safe["usage_authorization"] = metadata["usage_authorization"]
    renditions = metadata.get("renditions", [])
    entries = list(renditions.values()) if isinstance(renditions, dict) else renditions
    if not isinstance(entries, (list, tuple)):
        entries = []
    selected = next((item for item in entries if isinstance(item, dict)
                     and item.get("url") == candidate.preview_url), {})
    dimensions = re.fullmatch(r"(\d+)x(\d+)", candidate.resolution)
    width = selected.get("width", int(dimensions[1]) if dimensions else 0)
    height = selected.get("height", int(dimensions[2]) if dimensions else 0)
    width = width if type(width) is int and width >= 0 else 0
    height = height if type(height) is int and height >= 0 else 0
    rendition_id = hashlib.sha256(candidate.preview_url.encode()).hexdigest()
    safe["selected_rendition"] = {"identifier": rendition_id, "width": width, "height": height}
    return {"provider": candidate.provider, "source_id": _safe_text(candidate.source_id),
            "source_url": _safe_url(candidate.source_url), "creator": _safe_text(candidate.creator),
            "rights_status": _safe_text(candidate.rights_status), "source_metadata": safe,
            "rendition_identifier": rendition_id, "width": width, "height": height,
            "resolution": _safe_text(candidate.resolution), "duration": candidate.duration
            if math.isfinite(candidate.duration) else 0}


def _check_cancel(cancelled):
    if cancelled():
        raise AcquisitionCancelled("Acquisition cancelled.")


def _read_verified(path: Path, candidate: CandidateRecord, max_bytes: int | None) -> dict:
    if path.is_symlink() or path.parent.is_symlink():
        raise AcquisitionError("Unsafe cache entry.")
    if path.name != "manifest.json" or path.stat().st_size > 128 * 1024:
        raise AcquisitionError("Invalid cache manifest.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    limit = payload.get("byte_limit")
    if type(limit) is not int or limit <= 0:
        raise AcquisitionError("Invalid cache byte limit.")
    max_bytes = min(max_bytes, limit) if max_bytes is not None else limit
    media = path.parent / "media.mp4"
    if (payload.get("format") != FORMAT or payload.get("cache_key") != cache_key(candidate)
            or payload.get("provider") != candidate.provider
            or payload.get("source_id") != candidate.source_id
            or payload.get("usage_authorization") != "user_authorized_acquisition"
            or payload.get("local_path") != str(media.resolve())
            or media.is_symlink() or not media.is_file()
            or not 0 < media.stat().st_size <= max_bytes):
        raise AcquisitionError("Invalid cache entry.")
    fingerprint = fingerprint_file(media)
    if (payload.get("size_bytes") != fingerprint.size_bytes
            or payload.get("sha256") != fingerprint.sha256):
        raise AcquisitionError("Cache integrity check failed.")
    return payload


def verified_candidate_path(candidate: CandidateRecord) -> Path | None:
    if not candidate.acquisition_manifest or candidate.provider not in {"pexels", "pixabay"}:
        return None
    try:
        path = Path(candidate.acquisition_manifest)
        payload = _read_verified(path, candidate, None)
        return Path(payload["local_path"])
    except (OSError, ValueError, TypeError, AttributeError, AcquisitionError):
        return None


class AcquisitionService:
    def __init__(self, cache_root: str | Path | None = None, *, transport=None,
                 max_bytes: int = DEFAULT_MAX_BYTES, timeout: float = 20,
                 deadline: float = 300, probe=None):
        if max_bytes <= 0 or not 0 < timeout <= 60 or not 0 < deadline <= 3600:
            raise ValueError("Invalid acquisition limits.")
        self.root = Path(cache_root) if cache_root is not None else default_cache_root()
        self.transport = transport or StreamingTransport()
        self.max_bytes, self.timeout, self.deadline = max_bytes, timeout, deadline
        self.probe = probe if probe is not None else FFprobeMediaProbe()

    def acquire(self, request: AcquisitionRequest, *, progress=lambda done, total: None,
                cancelled=lambda: False) -> AcquisitionResult:
        staging = None
        try:
            candidate, review = request.candidate, request.review.normalized()
            if (request.user_authorized is not True or review.decision != "accepted"
                    or (review.scene_id, review.candidate_id, review.provider, review.source_id) !=
                    (candidate.scene_id, candidate.candidate_id, candidate.provider, candidate.source_id)):
                raise AcquisitionError("Matching accepted review and explicit authorization required.")
            if candidate.provider not in {"pexels", "pixabay"}:
                raise AcquisitionError("Provider does not support acquisition.")
            if not candidate.source_id.startswith(candidate.provider + ":") or not candidate.source_id.split(":", 1)[1].strip():
                raise AcquisitionError("Stable provider source identity required.")
            validate_url(candidate.preview_url)
            _check_cancel(cancelled)
            key = cache_key(candidate)
            self.root.mkdir(parents=True, exist_ok=True)
            destination = self.root.resolve() / key
            manifest = destination / "manifest.json"
            if destination.exists():
                # Fail closed, retaining unowned or corrupted entries for inspection.
                payload = _read_verified(manifest, candidate, self.max_bytes)
                _check_cancel(cancelled)
                return self._result(candidate, manifest, payload, True)
            staging = Path(tempfile.mkdtemp(prefix=".partial-", dir=self.root))
            partial = staging / "media.part"
            started = time.monotonic()
            done = 0
            digest = hashlib.sha256()
            with self.transport.open(candidate.preview_url, self.timeout) as response:
                if getattr(response, "status", 200) != 200:
                    raise AcquisitionError("Media HTTP request failed.")
                headers = response.headers
                content_type = headers.get("Content-Type", "").split(";", 1)[0].lower()
                if content_type not in {"video/mp4", "application/octet-stream", "binary/octet-stream"}:
                    raise AcquisitionError("Unsupported media content type.")
                length = headers.get("Content-Length")
                total = int(length) if length is not None else None
                if total is not None and not 0 < total <= self.max_bytes:
                    raise AcquisitionError("Media exceeds configured size limit or is empty.")
                progress(0, total)
                with partial.open("xb") as output:
                    while True:
                        _check_cancel(cancelled)
                        if time.monotonic() - started > self.deadline:
                            raise AcquisitionError("Acquisition deadline exceeded.")
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        done += len(chunk)
                        if done > self.max_bytes or (total is not None and done > total):
                            raise AcquisitionError("Media exceeds configured size limit.")
                        output.write(chunk)
                        digest.update(chunk)
                        progress(done, total)
                    output.flush()
                    os.fsync(output.fileno())
            _check_cancel(cancelled)
            if not done or (total is not None and done != total):
                raise AcquisitionError("Empty or truncated media response.")
            # API renditions are MP4. Reject HTML/JSON even with misleading MIME.
            with partial.open("rb") as handle:
                if handle.read(12)[4:8] != b"ftyp":
                    raise AcquisitionError("Invalid MP4 media header.")
            if getattr(self.probe, "executable", True):
                metadata = self.probe.probe(partial)
                if metadata.duration <= 0 or metadata.width <= 0 or metadata.height <= 0:
                    raise AcquisitionError("Media probe found no usable video.")
            media = staging / "media.mp4"
            os.replace(partial, media)
            payload = {"format": FORMAT, "cache_key": key, "cache_version": 1,
                       **_provenance(candidate), "local_path": str(destination / "media.mp4"),
                       "size_bytes": done, "sha256": digest.hexdigest(),
                       "byte_limit": self.max_bytes,
                       "acquired_at": datetime.now(timezone.utc).isoformat(),
                       "usage_authorization": "user_authorized_acquisition"}
            temp_manifest = staging / "manifest.tmp"
            temp_manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temp_manifest, staging / "manifest.json")
            fingerprint = fingerprint_file(media)
            if fingerprint.size_bytes != done or fingerprint.sha256 != payload["sha256"]:
                raise AcquisitionError("Downloaded media integrity check failed.")
            _check_cancel(cancelled)
            # Directory publication is atomic and does not replace existing entries.
            staging.rename(destination)
            staging = None
            return self._result(candidate, manifest, payload, False)
        except AcquisitionError:
            raise
        except Exception:
            # Never surface transport URLs, response bodies, headers or OS paths.
            raise AcquisitionError("Acquisition failed; no verified asset was published.") from None
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _result(candidate, manifest, payload, hit):
        return AcquisitionResult(replace(candidate, acquisition_manifest=str(manifest)),
                                 Path(payload["local_path"]), manifest,
                                 payload["size_bytes"], payload["sha256"], hit)
