from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


class FrameHashExtractor:
    """Tiny dependency-free perceptual hash using FFmpeg grayscale pixels."""

    def __init__(self, executable: str | None = None, timeout: float = 60.0):
        self.executable = (
            executable
            or os.environ.get("BIN_FINDER_FFMPEG", "").strip()
            or shutil.which("ffmpeg")
            or ""
        )
        self.timeout = timeout

    def hash_media(self, path: str | Path) -> str:
        if not self.executable:
            return ""
        media_path = Path(path)
        if not media_path.exists() or not media_path.is_file():
            return ""

        command = [
            self.executable,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(media_path),
            "-vf",
            "thumbnail,scale=9:8,format=gray",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                timeout=self.timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if completed.returncode != 0 or len(completed.stdout) < 72:
            return ""
        pixels = completed.stdout[:72]
        bits = 0
        bit_count = 0
        for row in range(8):
            offset = row * 9
            for column in range(8):
                left = pixels[offset + column]
                right = pixels[offset + column + 1]
                bits = (bits << 1) | int(left > right)
                bit_count += 1
        if bit_count != 64:
            return ""
        return f"{bits:016x}"


def hamming_similarity(left: str, right: str) -> float:
    if len(left) != 16 or len(right) != 16:
        return 0.0
    try:
        distance = (int(left, 16) ^ int(right, 16)).bit_count()
    except ValueError:
        return 0.0
    return round(max(0.0, 1.0 - distance / 64.0), 6)
