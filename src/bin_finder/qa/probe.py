"""Bounded local media processes and tolerant pure parsers."""
import json
import math
from pathlib import Path
import re
import subprocess

from bin_finder.production.config import ProductionConfig

VIDEO_FILTER = "blackdetect=d=0.5:pix_th=0.10,freezedetect=n=0.003:d=2"
AUDIO_FILTER = "silencedetect=n=-45dB:d=1.5,ebur128=peak=true"
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+|inf)"


def run_process(arguments: list[str], timeout: float = 600) -> subprocess.CompletedProcess:
    """Run without a shell and keep external diagnostics private."""
    return subprocess.run(arguments, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, check=True)


def parse_probe(payload: dict | str) -> dict:
    """Read the first video and audio streams."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    result = {"video": None, "audio": None, "duration": None}
    if video:
        try:
            numerator, denominator = video.get("avg_frame_rate", "0/1").split("/")
            fps = float(numerator) / float(denominator)
        except (ValueError, ZeroDivisionError):
            fps = None
        result["video"] = dict(codec=video.get("codec_name"), width=video.get("width"),
                               height=video.get("height"), fps=fps, pix_fmt=video.get("pix_fmt"))
    if audio:
        result["audio"] = dict(codec=audio.get("codec_name"), sample_rate=audio.get("sample_rate"),
                               channels=audio.get("channels"))
    try:
        duration = float(payload.get("format", {}).get("duration"))
        result["duration"] = duration if math.isfinite(duration) else None
    except (TypeError, ValueError):
        pass
    return result


def probe_video(path: Path, config: ProductionConfig) -> dict:
    """Inspect container metadata."""
    result = run_process([config.ffprobe, "-v", "error", "-show_streams", "-show_format",
                          "-of", "json", str(path)], 60)
    return parse_probe(result.stdout)


def parse_analysis(stderr: str, duration: float | None = None) -> dict:
    """Pair detector events and read the final loudness summary."""
    result = {"black": [], "freeze": [], "silence": [], "parse_notes": []}
    for kind, prefix in (("black", "black"), ("freeze", "freeze"), ("silence", "silence")):
        pending = None
        pattern = rf"{prefix}_(start|end)\s*[:=]\s*({NUMBER})"
        for match in re.finditer(pattern, stderr):
            value = float(match.group(2))
            if not math.isfinite(value):
                continue
            if match.group(1) == "start":
                pending = value
            elif pending is not None:
                if value >= pending:
                    result[kind].append([pending, value])
                pending = None
            else:
                result["parse_notes"].append(f"Thiếu mốc bắt đầu {kind}.")
        if pending is not None:
            if duration is not None and duration >= pending:
                result[kind].append([pending, duration])
            else:
                result["parse_notes"].append(f"Thiếu mốc kết thúc {kind}.")
    summary = stderr.rsplit("Summary:", 1)[-1]
    for key, label in (("lufs", "I"), ("lra", "LRA"), ("true_peak", "Peak")):
        matches = re.findall(rf"\b{label}:\s*({NUMBER})", summary)
        value = float(matches[-1]) if matches else None
        result[key] = value if value is not None and math.isfinite(value) else None
        if result[key] is None:
            result["parse_notes"].append(f"Không đọc được {label}.")
    return result


def analyze_video(path: Path, config: ProductionConfig, duration: float | None = None) -> dict:
    """Decode the entire video once for all detectors."""
    result = run_process([config.ffmpeg, "-hide_banner", "-nostats", "-i", str(path),
                          "-vf", VIDEO_FILTER, "-af", AUDIO_FILTER, "-f", "null", "-"])
    return parse_analysis(result.stderr, duration)


def analyze_audio(path: Path, config: ProductionConfig, duration: float | None = None) -> dict:
    """Measure decoded audio without decoding video."""
    result = run_process([config.ffmpeg, "-hide_banner", "-nostats", "-i", str(path),
                          "-map", "0:a:0", "-af", AUDIO_FILTER, "-f", "null", "-"])
    return parse_analysis(result.stderr, duration)
