"""Two-pass loudness normalization with video stream copy."""
import json
import math
from pathlib import Path

from bin_finder.production.config import ProductionConfig
from .probe import analyze_audio, probe_video, run_process

AAC_TRUE_PEAK_HEADROOM_DB = 0.5


def parse_loudnorm(stderr: str) -> dict:
    """Find a complete measurement object among FFmpeg diagnostics."""
    decoder = json.JSONDecoder()
    required = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    for position, character in enumerate(stderr):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(stderr[position:])
            if all(key in payload and math.isfinite(float(payload[key])) for key in required):
                return {key: float(payload[key]) for key in required}
        except (ValueError, TypeError):
            continue
    raise ValueError("Không đọc được phép đo loudnorm hữu hạn.")


def normalize_loudness(input: Path, output: Path, target_lufs: float = -14,
                       true_peak: float = -1, lra: float = 11,
                       config: ProductionConfig | None = None) -> dict[str, float]:
    """Measure, normalize audio, copy video and verify duration."""
    config = config or ProductionConfig()
    input = Path(input)
    output = Path(output)
    if input.resolve() == output.resolve() or output.exists():
        raise ValueError("File xuất phải mới và khác file đầu vào.")
    if not all(math.isfinite(value) for value in (target_lufs, true_peak, lra)):
        raise ValueError("Mục tiêu loudness không hợp lệ.")
    original = probe_video(input, config)
    base = f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}"
    measured = run_process([config.ffmpeg, "-hide_banner", "-nostats", "-i", str(input),
                            "-map", "0:a:0", "-af", base + ":print_format=json", "-f", "null", "-"])
    values = parse_loudnorm(measured.stderr)
    mapping = {"measured_I": "input_i", "measured_TP": "input_tp", "measured_LRA": "input_lra",
               "measured_thresh": "input_thresh", "offset": "target_offset"}
    safe_base = f"loudnorm=I={target_lufs}:TP={true_peak - AAC_TRUE_PEAK_HEADROOM_DB}:LRA={lra}"
    second = safe_base + ":" + ":".join(f"{key}={values[source]}" for key, source in mapping.items()) + ":linear=true"
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_process([config.ffmpeg, "-hide_banner", "-nostats", "-n", "-i", str(input),
                     "-map", "0:v:0", "-map", "0:a:0", "-af", second, "-c:v", "copy",
                     "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(output)])
        exported = probe_video(output, config)
        if original["duration"] is None or exported["duration"] is None or abs(original["duration"] - exported["duration"]) > 0.1:
            raise ValueError("Thời lượng thay đổi sau chuẩn hóa.")
        measurements = analyze_audio(output, config, exported["duration"])
        if measurements["lufs"] is None or measurements["true_peak"] is None:
            raise ValueError("Không đọc được loudness sau xuất.")
        return {"target_lufs": target_lufs, "true_peak": true_peak,
                "measured_lufs": measurements["lufs"], "measured_true_peak": measurements["true_peak"]}
    except Exception:
        output.unlink(missing_ok=True)
        raise
