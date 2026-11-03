"""Run offline video QA and optionally export normalized audio."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import sys

from bin_finder.production.config import ProductionConfig
from bin_finder.production.timeline import Timeline
from .checks import run_checks
from .export import normalize_loudness
from .models import Finding, QaReport, summarize_findings
from .probe import analyze_video, probe_video
from .report import write_html_report, write_json_report


def evaluate(video: Path, production: Path, timeline: Timeline, credits: str | None,
             config: ProductionConfig, check_sources: bool, target_lufs: float) -> QaReport:
    """Measure media and retain process failures as blocking findings."""
    findings = []
    metadata = {}
    analysis = {}
    try:
        print("Probe video…")
        metadata = probe_video(video, config)
    except (OSError, ValueError, subprocess.SubprocessError):
        findings.append(Finding("unreadable_video", "blocker", "Không mở được video bằng ffprobe."))
    if metadata.get("video") and metadata.get("audio"):
        try:
            print("Phân tích hình và âm thanh…")
            analysis = analyze_video(video, config, metadata.get("duration"))
        except (OSError, ValueError, subprocess.SubprocessError):
            findings.append(Finding("analysis_failed", "blocker", "Không phân tích được toàn bộ video."))
    print("Kiểm tra timeline, nguồn, quyền và chữ…")
    findings.extend(run_checks(metadata, analysis, timeline, config, credits, check_sources,
                               production.parent, target_lufs))
    return QaReport(str(video), str(production), datetime.now(timezone.utc).isoformat(),
                    findings, {**metadata, **analysis})


def save_report(report: QaReport, timeline: Timeline, directory: Path, suffix: str = "") -> None:
    """Publish both report formats and a short terminal summary."""
    directory.mkdir(parents=True, exist_ok=True)
    base = directory / ("qa-report" + suffix)
    print("Ghi báo cáo…")
    write_json_report(report, base.with_suffix(base.suffix + ".json"))
    write_html_report(report, timeline, base.with_suffix(base.suffix + ".html"))
    print("ĐẠT" if report.passed else "CHƯA ĐẠT")
    for level in ("blocker", "warning", "info"):
        print(f"{level}: {sum(item.severity == level for item in report.findings)}")
    for line in summarize_findings(report.findings)[:10]:
        print(line)
    print(f"Báo cáo: {base}.json / {base}.html")


def validate_input(timeline: Timeline, target_lufs: float) -> None:
    """Reject malformed types and nonfinite times before measurement."""
    def finite(value: object) -> bool:
        return type(value) in (int, float) and math.isfinite(value)

    if not finite(target_lufs) or not -70 <= target_lufs <= -5:
        raise ValueError("Invalid loudness target")
    if not finite(timeline.duration) or timeline.duration <= 0:
        raise ValueError("Invalid duration")
    if type(timeline.subtitles) is not bool or not finite(timeline.end_hold) or timeline.end_hold < 0:
        raise ValueError("Invalid production options")
    for shot in timeline.shots:
        if not all(finite(getattr(shot, name)) for name in ("start", "end", "clip_in", "clip_out", "speed")):
            raise ValueError("Invalid shot timing")
        if not all(isinstance(getattr(shot, name), str) for name in ("cue_id", "text", "source_id", "provider", "local_path", "origin")):
            raise ValueError("Invalid shot identity")
        if shot.license is not None and not isinstance(shot.license, dict):
            raise ValueError("Invalid license")
        if not isinstance(shot.notes, list) or not all(isinstance(note, str) for note in shot.notes):
            raise ValueError("Invalid notes")
        for name in ("source_url", "creator", "license_name"):
            if (shot.license or {}).get(name) is not None and not isinstance(shot.license[name], str):
                raise ValueError("Invalid license metadata")
    for word in timeline.words:
        if not finite(word["start"]) or not finite(word["end"]) or not isinstance(word["word"], str):
            raise ValueError("Invalid word")


def main(argv: list[str] | None = None) -> int:
    """Return 2 for invalid input and 3 for strict QA failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--production", type=Path)
    parser.add_argument("--credits", type=Path)
    parser.add_argument("-o", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--check-sources", action="store_true")
    parser.add_argument("--export", type=Path, dest="export_path")
    parser.add_argument("--target-lufs", type=float, default=-14)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args(argv)
    try:
        if not arguments.video.is_file():
            raise ValueError("missing video")
        production = arguments.production or arguments.video.parent / "production.json"
        credits_path = arguments.credits or arguments.video.parent / "credits.txt"
        payload = json.loads(production.read_text(encoding="utf-8-sig"))
        for shot in payload["shots"]:
            for name, default in (("license", {}), ("source_id", ""), ("local_path", "")):
                shot.setdefault(name, default)
        timeline = Timeline.from_dict(payload)
        validate_input(timeline, arguments.target_lufs)
        credits = credits_path.read_text(encoding="utf-8-sig") if credits_path.is_file() else None
        config = ProductionConfig.load(arguments.project_root)
        directory = arguments.o or arguments.video.parent
        report = evaluate(arguments.video, production, timeline, credits, config,
                          arguments.check_sources, arguments.target_lufs)
        save_report(report, timeline, directory)
        if arguments.export_path and (report.passed or not arguments.strict):
            if not report.passed:
                print("CẢNH BÁO: vẫn xuất dù còn lỗi chặn vì không bật --strict.")
            print("Xuất bản chuẩn hóa loudness…")
            measurements = normalize_loudness(arguments.video, arguments.export_path, arguments.target_lufs, config=config)
            print(f"Loudness đo sau xuất: {measurements['measured_lufs']:.1f} LUFS; true peak: {measurements['measured_true_peak']:.1f} dBFS")
            report = evaluate(arguments.export_path, production, timeline, credits, config,
                              arguments.check_sources, arguments.target_lufs)
            save_report(report, timeline, directory, ".final")
        return 3 if arguments.strict and not report.passed else 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError):
        print("Lỗi đầu vào hoặc xuất media; kiểm tra file và cấu hình cục bộ.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
