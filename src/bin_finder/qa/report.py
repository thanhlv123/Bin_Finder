"""Self-contained Vietnamese QA reports."""
import html
import json
from pathlib import Path, PureWindowsPath
import re

from bin_finder.production.timeline import Timeline
from .models import QaReport, sorted_findings


def write_json_report(report: QaReport, output: Path) -> None:
    """Write portable UTF-8 JSON."""
    output.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def safe_text(value: object) -> str:
    """Escape markup and redact absolute local paths in displayed prose."""
    text = str(value)
    text = re.sub(r"[A-Za-z]:[\\/][^\s<>\"']+", lambda match: PureWindowsPath(match[0]).name, text)
    text = re.sub(r"(?<![:/\w])/(?:[^/\s<>]+/)+[^\s<>]*", lambda match: Path(match[0]).name, text)
    return html.escape(text)


def timestamp(value: float | None) -> str:
    if value is None:
        return "—"
    minutes, seconds = divmod(value, 60)
    return f"{int(minutes):02d}:{seconds:04.1f}"


def write_html_report(report: QaReport, timeline: Timeline, output: Path) -> None:
    """Render escaped tables without scripts or external resources."""
    levels = {"blocker": "Lỗi chặn", "warning": "Cảnh báo", "info": "Thông tin"}
    counts = {level: sum(item.severity == level for item in report.findings) for level in levels}
    metrics = report.metrics
    video = metrics.get("video") or {}
    summary = ["ĐẠT" if report.passed else "CHƯA ĐẠT", Path(report.video_path).name]
    summary.extend(f"{label}: {counts[level]}" for level, label in levels.items())
    summary.extend([f"Thời lượng: {metrics.get('duration', '—')} s",
                    f"Độ phân giải: {video.get('width', '—')}×{video.get('height', '—')}",
                    f"Loudness: {metrics.get('lufs', '—')} LUFS", f"True peak: {metrics.get('true_peak', '—')} dBFS"])
    cards = "".join(f"<span>{safe_text(value)}</span>" for value in summary)
    findings = sorted_findings(report.findings)
    rows = []
    for finding in findings:
        values = [levels[finding.severity], finding.code, finding.cue_id or "—",
                  timestamp(finding.start) + (" – " + timestamp(finding.end) if finding.end is not None else ""), finding.message]
        rows.append("<tr>" + "".join(f"<td>{safe_text(value)}</td>" for value in values) + "</tr>")
    shots = []
    for shot in timeline.shots:
        values = [shot.cue_id, shot.text, shot.source_id, shot.provider,
                  (shot.license or {}).get("license_name", "—"), shot.origin, f"{shot.end - shot.start:.2f} s"]
        shots.append("<tr>" + "".join(f"<td>{safe_text(value)}</td>" for value in values) + "</tr>")
    document = ('<!doctype html><html lang="vi"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width"><title>Báo cáo kiểm tra video</title>'
                '<style>body{font:16px system-ui;margin:2rem;color:#182230}table{border-collapse:collapse;width:100%;margin:1rem 0}td,th{border:1px solid #ccd;padding:.6rem;text-align:left;overflow-wrap:anywhere}span{display:inline-block;padding:.8rem;background:#eef2f8;margin:.3rem}h1{color:#234}</style>'
                '<h1>Báo cáo kiểm tra video</h1>' + cards + '<h2>Kết quả kiểm tra</h2>'
                '<table><tr><th>Mức</th><th>Mã</th><th>Cue</th><th>Thời điểm</th><th>Mô tả</th></tr>'
                + "".join(rows) + '</table><h2>Danh sách shot</h2><table><tr><th>Cue</th><th>Câu</th><th>Nguồn</th><th>Provider</th><th>License</th><th>Origin</th><th>Thời lượng</th></tr>'
                + "".join(shots) + '</table></html>')
    output.write_text(document, encoding="utf-8")
