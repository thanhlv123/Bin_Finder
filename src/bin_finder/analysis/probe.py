from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from bin_finder.analysis.models import MediaMetadata


class MediaProbeError(RuntimeError):
    pass


class MediaProbeUnavailable(MediaProbeError):
    pass


def _fraction(value: str) -> float:
    raw = (value or "").strip()
    if not raw or raw in {"0/0", "N/A"}:
        return 0.0
    if "/" in raw:
        left, right = raw.split("/", 1)
        try:
            denominator = float(right)
            return float(left) / denominator if denominator else 0.0
        except ValueError:
            return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def metadata_from_ffprobe(payload: dict[str, Any]) -> MediaMetadata:
    streams = payload.get("streams") or []
    format_info = payload.get("format") or {}
    video_stream = next(
        (
            item for item in streams
            if isinstance(item, dict) and item.get("codec_type") == "video"
        ),
        {},
    )
    audio_stream = next(
        (
            item for item in streams
            if isinstance(item, dict) and item.get("codec_type") == "audio"
        ),
        None,
    )
    duration_values = [
        video_stream.get("duration"),
        format_info.get("duration") if isinstance(format_info, dict) else None,
    ]
    duration = 0.0
    for raw in duration_values:
        try:
            duration = float(raw)
        except (TypeError, ValueError):
            continue
        if duration > 0:
            break

    fps = _fraction(str(video_stream.get("avg_frame_rate") or ""))
    if fps <= 0:
        fps = _fraction(str(video_stream.get("r_frame_rate") or ""))

    return MediaMetadata(
        duration=max(0.0, duration),
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        fps=max(0.0, fps),
        codec=str(video_stream.get("codec_name") or ""),
        has_audio=audio_stream is not None,
    )


class FFprobeMediaProbe:
    def __init__(self, executable: str | None = None, timeout: float = 30.0):
        self.executable = (
            executable
            or os.environ.get("BIN_FINDER_FFPROBE", "").strip()
            or shutil.which("ffprobe")
            or ""
        )
        self.timeout = timeout

    def probe(self, path: str | Path) -> MediaMetadata:
        if not self.executable:
            raise MediaProbeUnavailable("FFprobe chưa được tìm thấy trong PATH.")
        command = [
            self.executable,
            "-v", "error",
            "-print_format", "json",
            "-show_streams",
            "-show_format",
            str(Path(path)),
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
            raise MediaProbeError(f"FFprobe không thể phân tích media: {exc.__class__.__name__}") from None
        if completed.returncode != 0:
            raise MediaProbeError(f"FFprobe trả về mã lỗi {completed.returncode}.")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            raise MediaProbeError("FFprobe trả về JSON không hợp lệ.") from None
        if not isinstance(payload, dict):
            raise MediaProbeError("FFprobe trả về dữ liệu không hợp lệ.")
        return metadata_from_ffprobe(payload)
