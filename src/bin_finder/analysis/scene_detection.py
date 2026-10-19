from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from bin_finder.analysis.models import ShotSegment


_PTS_TIME_RE = re.compile(r"pts_time:(?P<value>-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class ShotDetectionResult:
    shots: tuple[ShotSegment, ...]
    backend: str
    warning: str = ""


def build_shots(cut_times: list[float], duration: float) -> tuple[ShotSegment, ...]:
    if duration <= 0:
        return ()
    cuts = sorted(
        {
            round(value, 6)
            for value in cut_times
            if 0.0 < value < duration
        }
    )
    boundaries = [0.0, *cuts, duration]
    shots = [
        ShotSegment(index=index, start=start, end=end)
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1)
        if end > start
    ]
    return tuple(shots)


def parse_ffmpeg_scene_times(stderr: str) -> list[float]:
    times: list[float] = []
    for match in _PTS_TIME_RE.finditer(stderr or ""):
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        if value >= 0:
            times.append(value)
    return times


class FfmpegSceneDetector:
    """Dependency-free shot detector using the user's FFmpeg runtime."""

    def __init__(
        self,
        executable: str | None = None,
        threshold: float = 0.35,
        timeout: float = 120.0,
    ):
        self.executable = (
            executable
            or os.environ.get("BIN_FINDER_FFMPEG", "").strip()
            or shutil.which("ffmpeg")
            or ""
        )
        self.threshold = max(0.05, min(float(threshold), 0.95))
        self.timeout = timeout

    def detect(self, path: str | Path, duration: float) -> ShotDetectionResult:
        if duration <= 0:
            return ShotDetectionResult((), "ffmpeg", "Không xác định được duration để chia shot.")
        if not self.executable:
            return ShotDetectionResult(
                build_shots([], duration),
                "single-shot-fallback",
                "FFmpeg chưa được tìm thấy; tạm coi toàn bộ video là một shot.",
            )

        filter_expression = f"select='gt(scene,{self.threshold:.3f})',showinfo"
        command = [
            self.executable,
            "-hide_banner",
            "-nostdin",
            "-i", str(Path(path)),
            "-an",
            "-vf", filter_expression,
            "-f", "null",
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ShotDetectionResult(
                build_shots([], duration),
                "single-shot-fallback",
                f"Scene detection fallback: {exc.__class__.__name__}",
            )
        if completed.returncode != 0:
            return ShotDetectionResult(
                build_shots([], duration),
                "single-shot-fallback",
                f"FFmpeg scene detection trả về mã lỗi {completed.returncode}.",
            )
        cuts = parse_ffmpeg_scene_times(completed.stderr)
        return ShotDetectionResult(build_shots(cuts, duration), "ffmpeg-scene")
