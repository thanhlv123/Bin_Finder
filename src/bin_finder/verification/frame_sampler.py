"""Bounded in-memory FFmpeg frame sampling for VLM verification. No temp files, no network."""
from __future__ import annotations

import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FrameSamplingError(Exception):
    """Sampling failed safely; ``code`` is a short stable identifier."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class FrameSamplingPolicy:
    frames: int = 3                    # default 20% / 50% / 80% of the unit
    max_frames: int = 6
    max_width: int = 960               # downscale only; aspect ratio preserved
    max_frame_bytes: int = 2_000_000   # per JPEG, enforced by ffmpeg -fs and re-checked
    timeout: float = 30.0              # per frame

    def validate(self) -> None:
        if not 1 <= self.frames <= self.max_frames:
            raise ValueError("frames must be within 1..max_frames")
        if self.max_width < 16 or self.max_frame_bytes < 1024 or self.timeout <= 0:
            raise ValueError("invalid frame bounds")


def sample_times(start: float, end: float, frames: int) -> tuple[float, ...]:
    """Deterministic timestamps strictly inside [start, end]: 20%..80% of the unit."""
    if not (isinstance(start, (int, float)) and isinstance(end, (int, float))
            and math.isfinite(start) and math.isfinite(end)) or start < 0 or end <= start:
        raise FrameSamplingError("invalid-range")
    duration = end - start
    fractions = (0.5,) if frames == 1 else tuple(
        0.2 + 0.6 * index / (frames - 1) for index in range(frames))
    return tuple(round(start + duration * fraction, 3) for fraction in fractions)


def _plain_file(path: Path) -> bool:
    try:
        return (not any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))
                and path.is_file())
    except OSError:
        return False


class FfmpegFrameSampler:
    def __init__(self, executable: str | None = None, policy: FrameSamplingPolicy | None = None):
        self.executable = (executable or os.environ.get("BIN_FINDER_FFMPEG", "").strip()
                           or shutil.which("ffmpeg") or "")
        self.policy = policy or FrameSamplingPolicy()
        self.policy.validate()

    def sample(self, source_path: str, start: float, end: float) -> tuple[bytes, ...]:
        """JPEG bytes for up to ``policy.frames`` frames, or raise FrameSamplingError."""
        times = sample_times(start, end, self.policy.frames)
        if not self.executable:
            raise FrameSamplingError("ffmpeg-unavailable")
        source = Path(source_path).expanduser().absolute()
        if not _plain_file(source):
            raise FrameSamplingError("source-unavailable")
        frames = []
        for timestamp in times:
            frame = self._frame(source, timestamp)
            if frame:
                frames.append(frame)
        if not frames:
            raise FrameSamplingError("no-frames")
        return tuple(frames)

    def _frame(self, source: Path, timestamp: float) -> bytes:
        policy = self.policy
        command = [
            self.executable, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", f"{timestamp:.3f}", "-i", str(source),
            "-frames:v", "1", "-vf", f"scale='min({policy.max_width},iw)':-2",
            "-pix_fmt", "yuvj420p", "-c:v", "mjpeg", "-q:v", "4",
            "-fs", str(policy.max_frame_bytes + 1), "-f", "image2pipe", "-",
        ]
        try:
            completed = subprocess.run(
                command, capture_output=True, timeout=policy.timeout, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            return b""
        data = completed.stdout
        if (completed.returncode != 0 or not data or len(data) > policy.max_frame_bytes
                or data[:3] != b"\xff\xd8\xff"):
            return b""
        return data
