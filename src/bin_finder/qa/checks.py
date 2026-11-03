"""Pure checks over media measurements and the production timeline."""
from difflib import SequenceMatcher
from pathlib import Path
import re
import unicodedata

from bin_finder.production.config import ProductionConfig
from bin_finder.production.subtitles import group_words
from bin_finder.production.timeline import Timeline
from .models import Finding

EXPORT_FIXABLE_CODES: frozenset[str] = frozenset({"loudness", "true_peak"})


def check_streams(metadata: dict, config: ProductionConfig) -> list[Finding]:
    """Validate required streams and delivery format."""
    findings = []
    video = metadata.get("video")
    if not video:
        findings.append(Finding("missing_video_stream", "blocker", "Không có luồng hình."))
    else:
        if (video.get("width"), video.get("height")) != (config.width, config.height):
            findings.append(Finding("resolution_mismatch", "blocker", "Độ phân giải không đúng cấu hình."))
        if video.get("fps") is None or abs(video["fps"] - config.fps) > 0.5:
            findings.append(Finding("fps_mismatch", "blocker", "Tốc độ khung hình không đúng cấu hình."))
        if video.get("codec") != "h264" or video.get("pix_fmt") != "yuv420p":
            findings.append(Finding("video_format", "warning", "Nên dùng H.264 và yuv420p."))
    if not metadata.get("audio"):
        findings.append(Finding("missing_audio_stream", "blocker", "Không có luồng âm thanh."))
    return findings


def check_timeline(metadata: dict, timeline: Timeline) -> list[Finding]:
    """Check duration and continuous shot boundaries."""
    findings = []
    duration = metadata.get("duration")
    if duration is None or abs(duration - timeline.duration) > 0.2:
        findings.append(Finding("duration_mismatch", "blocker", "Thời lượng MP4 khác timeline."))
    previous_end = None
    for shot in timeline.shots:
        if previous_end is not None and abs(shot.start - previous_end) > 0.05:
            findings.append(Finding("timeline_gap", "blocker", "Timeline có khoảng hở hoặc chồng.", shot.cue_id, shot.start))
        if shot.end <= shot.start:
            findings.append(Finding("invalid_shot_duration", "blocker", "Shot có thời lượng không hợp lệ.", shot.cue_id))
        previous_end = shot.end
    if not timeline.shots:
        findings.append(Finding("missing_shots", "blocker", "Timeline không có shot."))
    elif abs(previous_end - timeline.duration) > 0.2:
        findings.append(Finding("last_shot_end", "warning", "Shot cuối không khớp thời lượng."))
    return findings


def check_media(timeline: Timeline, credits: str | None, check_sources: bool = False,
                source_root: Path = Path(".")) -> list[Finding]:
    """Check media identity, licensing, credits and clip selection."""
    findings = []
    if credits is None:
        findings.append(Finding("missing_credits", "blocker", "Thiếu credits.txt."))
    source_cues = {}
    previous = None
    for shot in timeline.shots:
        def add(code: str, severity: str, message: str) -> None:
            findings.append(Finding(code, severity, message, shot.cue_id, shot.start, shot.end))
        if not shot.source_id or not shot.local_path:
            add("missing_media", "blocker", "Shot thiếu mã nguồn hoặc đường dẫn media.")
        elif not (source_root / shot.local_path).is_file():
            add("missing_source_file", "blocker" if check_sources else "warning", "Không tìm thấy file nguồn trong cache.")
        if shot.clip_out <= shot.clip_in:
            add("invalid_clip_range", "blocker", "Đoạn cắt không hợp lệ.")
        if not 0.5 <= shot.speed <= 2:
            add("clip_speed", "warning", "Tốc độ clip ngoài khoảng 0.5–2.0.")
        license_info = shot.license or {}
        if not license_info or license_info.get("usable_in_video") is not True or shot.provider.lower() == "youtube":
            add("unusable_license", "blocker", "Nguồn không được phép dùng trong video.")
        source_url = license_info.get("source_url")
        if not source_url or not license_info.get("license_name"):
            add("unclear_license", "warning", "Quyền chưa rõ: thiếu tên giấy phép hoặc URL nguồn.")
        if credits is not None and (not source_url or source_url not in credits):
            add("missing_source_credit", "blocker", "Nguồn chưa xuất hiện trong credits theo URL.")
        if license_info.get("attribution_required") is True:
            creator = license_info.get("creator")
            if not credits or not source_url or source_url not in credits or not creator or creator not in credits:
                add("missing_attribution", "blocker", "Credits thiếu URL hoặc tác giả bắt buộc.")
        if shot.origin == "suggested":
            add("suggested_clip", "warning", "Clip mới là gợi ý: " + shot.text)
        source_cues.setdefault(shot.source_id, []).append(shot.cue_id)
        if previous and previous.source_id == shot.source_id and max(previous.clip_in, shot.clip_in) < min(previous.clip_out, shot.clip_out):
            add("adjacent_overlap", "warning", "Hai shot kề dùng chồng đoạn cùng nguồn.")
        length = shot.end - shot.start
        if length < 1.5:
            add("short_shot", "warning", "Shot ngắn hơn 1.5 giây.")
        if length > 12:
            add("long_shot", "info", "Shot dài hơn 12 giây.")
        previous = shot
    for source_id, cue_ids in source_cues.items():
        if source_id and len(cue_ids) >= 2:
            findings.append(Finding("repeated_source", "warning", "Nguồn lặp ở cue: " + ", ".join(cue_ids), details={"source_id": source_id, "cue_ids": cue_ids}))
    return findings


def check_analysis(analysis: dict, timeline: Timeline, target_lufs: float = -14) -> list[Finding]:
    """Locate detector intervals in cues and assess audio levels."""
    findings = [Finding("analysis_parse", "info", note) for note in analysis.get("parse_notes", [])]
    last_word_end = max((word["end"] for word in timeline.words), default=timeline.duration)
    for kind, minimum in (("black", 0.5), ("freeze", 2), ("silence", 1.5)):
        for start, end in analysis.get(kind, []):
            if end - start < minimum:
                continue
            shots = [shot for shot in timeline.shots if shot.start < end and shot.end > start]
            cue_ids = ", ".join(dict.fromkeys(shot.cue_id for shot in shots)) or None
            if kind == "silence":
                if end >= timeline.duration - 0.1 and start >= last_word_end - 0.05:
                    continue
                end = min(end, last_word_end) if end >= timeline.duration - 0.1 else end
                if end - start < minimum:
                    continue
                severity = "blocker" if end - start >= 3 else "warning"
                message = "Khoảng im lặng trong lời đọc."
                code = "silence"
            else:
                continue
            findings.append(Finding(code, severity, message, cue_ids, start, end))
    findings.extend(check_visual_ranges(analysis, timeline))
    loudness = analysis.get("lufs")
    if loudness is not None and abs(loudness - target_lufs) > 2:
        severity = "blocker" if abs(loudness - target_lufs) > 5 else "warning"
        findings.append(Finding("loudness", severity, f"Loudness {loudness:.1f} LUFS lệch mục tiêu {target_lufs:g}."))
    if analysis.get("true_peak") is not None and analysis["true_peak"] > -1:
        findings.append(Finding("true_peak", "warning", "True peak vượt −1 dBFS."))
    return findings


def check_visual_ranges(analysis: dict, timeline: Timeline) -> list[Finding]:
    """Group visual detector intervals by concrete timeline shot."""
    findings: list[Finding] = []
    for kind, minimum in (("black", 0.5), ("freeze", 2)):
        groups: dict[int | None, list[list[float]]] = {}
        for start, end in analysis.get(kind, []):
            if end - start < minimum:
                continue
            matched = False
            for index, shot in enumerate(timeline.shots):
                if shot.start < end and shot.end > start:
                    groups.setdefault(index, []).append([max(start, shot.start), min(end, shot.end)])
                    matched = True
            if not matched:
                groups.setdefault(None, []).append([start, end])
        for index, ranges in groups.items():
            shot = timeline.shots[index] if index is not None else None
            ranges.sort()
            merged: list[list[float]] = []
            for start, end in ranges:
                if merged and start <= merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], end)
                else:
                    merged.append([start, end])
            duration = sum(end - start for start, end in merged)
            if kind == "black":
                severity = "warning" if all(end <= 0.5 or start >= timeline.duration - 0.5 for start, end in merged) else "blocker"
                message = f"Phát hiện hình đen tổng {duration:.2f} giây"
                advice = "clip nguồn có thể quá tối, nên chọn clip khác"
                code = "black_frames"
            else:
                intentional = shot is not None and any(token in " ".join(shot.notes).lower() for token in ("hold", "freeze", "ken burns", "ken_burns", "giữ frame", "final frame"))
                severity = "info" if intentional else "warning"
                message = f"Phát hiện đứng hình tổng {duration:.2f} giây"
                advice = "kiểm tra chuyển động clip nguồn, nên chọn clip khác nếu ngoài ý muốn"
                code = "freeze_frames"
            details = {"ranges": merged, "total_duration": duration,
                       "source_id": shot.source_id if shot else None, "provider": shot.provider if shot else None}
            if shot:
                source = shot.source_id if shot.source_id.startswith(shot.provider + ":") else f"{shot.provider}:{shot.source_id}"
                message += f" trong clip {source} (cue {shot.cue_id}) — {advice}."
            else:
                message += "; không xác định được shot nguồn."
            findings.append(Finding(code, severity, message, shot.cue_id if shot else None,
                                    merged[0][0], merged[-1][1], details))
    return findings


def normalized_words(text: str) -> list[str]:
    """Normalize Unicode, case and punctuation for ordered comparison."""
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold())


def check_words(timeline: Timeline) -> list[Finding]:
    """Check word timing, text coverage and shared subtitle groups."""
    findings = []
    if not timeline.words:
        return [Finding("missing_words", "blocker", "Không có mốc thời gian chữ.")]
    previous_start = -float("inf")
    for word in timeline.words:
        if word["end"] < word["start"] or word["start"] < previous_start:
            findings.append(Finding("word_order", "blocker", "Mốc chữ sai thứ tự.", start=word["start"]))
        if word["end"] > timeline.duration:
            findings.append(Finding("words_past_duration", "blocker", "Chữ kết thúc sau video.", start=word["start"]))
        previous_start = word["start"]
    expected = normalized_words(" ".join(shot.text for shot in timeline.shots))
    actual = normalized_words(" ".join(word["word"] for word in timeline.words))
    matcher = SequenceMatcher(None, expected, actual, autojunk=False)
    coverage = sum(block.size for block in matcher.get_matching_blocks()) / max(1, len(expected))
    if coverage < 0.98:
        findings.append(Finding("word_coverage", "blocker" if coverage < 0.9 else "warning", f"Tỉ lệ khớp chữ theo thứ tự: {coverage:.1%}.", details={"coverage": coverage}))
    if timeline.subtitles:
        previous_end = -float("inf")
        for group in group_words(timeline.words):
            start = group[0]["start"]
            end = group[-1]["end"]
            if start < previous_end or end - start < 0.3:
                findings.append(Finding("subtitle_timing", "warning", "Nhóm phụ đề chồng thời gian hoặc hiện dưới 0.3 giây.", start=start, end=end))
            previous_end = end
    return findings


def run_checks(metadata: dict, analysis: dict, timeline: Timeline, config: ProductionConfig,
               credits: str | None, check_sources: bool = False, source_root: Path = Path("."),
               target_lufs: float = -14) -> list[Finding]:
    """Collect all deterministic checks."""
    return (check_streams(metadata, config) + check_timeline(metadata, timeline)
            + check_media(timeline, credits, check_sources, source_root)
            + check_analysis(analysis, timeline, target_lufs) + check_words(timeline))
