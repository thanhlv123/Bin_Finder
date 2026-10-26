"""BF-S06: bounded FFmpeg export ONLY from an independently licensed LOCAL file.

The YouTube Data API metadata reference is NEVER an audiovisual input. This
module cannot download or resolve online video URLs and never accepts a
YouTube web URL as its source_path.

Permission is a positive user assertion about the separately obtained local
source file, not something inferred from a YouTube Creative Commons tag.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
import subprocess

from bin_finder.analysis.probe import FFprobeMediaProbe, MediaProbeError
from bin_finder.clips.extractor import FfmpegClipExtractor, ClipExtractionError
from bin_finder.clips.models import ClipProposal

_ALLOWED_PROVENANCE = frozenset({
    "user_owned_original_master",
    "licensed_independent_master_copy",
})
_FORMATS = {"clip": ".mp4", "still": ".jpg"}


class AuthorizedLocalCutError(ValueError):
    """Short fixed safe reasons only; no user-controlled filesystem paths."""


@dataclass(frozen=True)
class AuthorizedCutRequest:
    source_path: str
    source_root: str
    output_path: str
    output_root: str
    start_seconds: float
    duration_seconds: float
    mode: str
    provenance: str
    confirm_usage_rights: bool = False
    approve_local_cut: bool = False


@dataclass(frozen=True)
class AuthorizedCutOutcome:
    status: str
    duration_seconds: float
    output_written: bool = False
    source_license_independently_verified: bool = False
    model_or_provider_calls: int = 0


def _safe_path(value: str, root: str, *, source: bool) -> Path:
    if not isinstance(value, str) or not isinstance(root, str):
        raise AuthorizedLocalCutError("invalid-local-path")
    candidate, base = Path(value), Path(root)
    if not candidate.is_absolute() or not base.is_absolute():
        raise AuthorizedLocalCutError("absolute-local-path-required")
    if not base.is_dir() or base.is_symlink() or getattr(base, "is_junction", lambda: False)():
        raise AuthorizedLocalCutError("invalid-local-root")
    if candidate.is_symlink() or getattr(candidate, "is_junction", lambda: False)():
        raise AuthorizedLocalCutError("unsafe-local-link")
    # Strict resolution for existing source, resolved containing folder for
    # exclusive-create output. Both must remain within the independent root.
    try:
        parent = candidate.parent.resolve(strict=True)
        trusted_root = base.resolve(strict=True)
        if not parent.is_relative_to(trusted_root):
            raise AuthorizedLocalCutError("path-outside-local-root")
        if any(
            part.is_symlink() or getattr(part, "is_junction", lambda: False)()
            for part in [candidate.parent, *candidate.parent.parents]
            if part.is_relative_to(base)
        ):
            raise AuthorizedLocalCutError("unsafe-local-link")
        if source:
            if not candidate.is_file():
                raise AuthorizedLocalCutError("local-media-not-found")
            actual = candidate.resolve(strict=True)
            if not actual.is_relative_to(trusted_root):
                raise AuthorizedLocalCutError("path-outside-local-root")
        else:
            if candidate.exists() or candidate.is_symlink():
                raise AuthorizedLocalCutError("output-already-exists")
            actual = parent / candidate.name
    except (OSError, RuntimeError):
        raise AuthorizedLocalCutError("invalid-local-path") from None
    return actual


def check_cut_request(req: AuthorizedCutRequest) -> tuple[Path, Path]:
    if not isinstance(req, AuthorizedCutRequest):
        raise AuthorizedLocalCutError("invalid-cut-request")
    if req.mode not in _FORMATS:
        raise AuthorizedLocalCutError("invalid-cut-mode")
    if req.provenance not in _ALLOWED_PROVENANCE:
        raise AuthorizedLocalCutError("unsupported-media-provenance")
    if (type(req.confirm_usage_rights) is not bool
            or type(req.approve_local_cut) is not bool):
        raise AuthorizedLocalCutError("invalid-cut-approval")
    for x in (req.start_seconds, req.duration_seconds):
        if type(x) not in (int, float) or not math.isfinite(x):
            raise AuthorizedLocalCutError("invalid-cut-time")
    if (req.start_seconds < 0 or
            not 1 <= req.duration_seconds <= 7):
        raise AuthorizedLocalCutError("cut-must-be-1-to-7-seconds")
    src = _safe_path(req.source_path, req.source_root, source=True)
    dst = _safe_path(req.output_path, req.output_root, source=False)
    if src.suffix.casefold() not in {".mp4", ".mov", ".mkv", ".m4v"}:
        raise AuthorizedLocalCutError("unsupported-local-source-type")
    if dst.suffix.casefold() != _FORMATS[req.mode]:
        raise AuthorizedLocalCutError("invalid-cut-output-extension")
    if src == dst:
        raise AuthorizedLocalCutError("source-equals-output")
    return src, dst


def export_authorized_local_cut(
    req: AuthorizedCutRequest, *, ffprobe=None, extractor=None,
) -> AuthorizedCutOutcome:
    """Create a 1–7s MP4 or one still held 1–7s by a later timeline.

    No execution without BOTH confirmation of usable local copy and explicit
    permission to process that local file. Neither check proves copyright.
    """
    src, dst = check_cut_request(req)
    if not req.confirm_usage_rights or not req.approve_local_cut:
        return AuthorizedCutOutcome("cut-approval-required", req.duration_seconds)

    try:
        media = (ffprobe or FFprobeMediaProbe()).probe(src)
    except (MediaProbeError, OSError, ValueError):
        return AuthorizedCutOutcome("local-media-probe-failed", req.duration_seconds)
    if (not math.isfinite(media.duration) or media.duration <= 0
            or media.width <= 0 or media.height <= 0
            or req.start_seconds + req.duration_seconds > media.duration + 0.005):
        return AuthorizedCutOutcome("cut-outside-local-video", req.duration_seconds)

    if req.mode == "clip":
        proposal = ClipProposal(
            unit_id="authorized_local_source",
            source_path=str(src),
            start=req.start_seconds,
            end=req.start_seconds + req.duration_seconds,
            score=0.0, accepted=True,
            reason="user-confirmed-local-source",
        )
        try:
            (extractor or FfmpegClipExtractor(
                timeout=120.0, reencode=True,
            )).extract(proposal, dst, overwrite=False)
        except (ClipExtractionError, OSError, ValueError):
            return AuthorizedCutOutcome("local-ffmpeg-export-failed",
                                        req.duration_seconds)
    else:
        # Still content captured at middle of selected 1–7s narration window.
        # A JPG is one frame, not a 7s animated media/video.
        import shutil
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            return AuthorizedCutOutcome("local-ffmpeg-unavailable", req.duration_seconds)
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
            "-ss", f"{req.start_seconds + req.duration_seconds / 2:.3f}",
            "-i", str(src), "-frames:v", "1", "-q:v", "2", str(dst),
        ]
        try:
            cp = subprocess.run(
                cmd, capture_output=True, timeout=120, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return AuthorizedCutOutcome("local-ffmpeg-export-failed", req.duration_seconds)
        if cp.returncode != 0:
            return AuthorizedCutOutcome("local-ffmpeg-export-failed", req.duration_seconds)
    if not dst.is_file() or dst.stat().st_size <= 0:
        return AuthorizedCutOutcome("local-ffmpeg-export-failed", req.duration_seconds)
    return AuthorizedCutOutcome("local-clip-created-pending-editorial-review",
                                req.duration_seconds, output_written=True)
