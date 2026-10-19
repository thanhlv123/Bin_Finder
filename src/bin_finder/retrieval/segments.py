from __future__ import annotations

from bin_finder.analysis.models import CandidateAnalysis, ShotSegment
from bin_finder.models import SceneRecord
from bin_finder.retrieval.models import RetrievalUnit


def build_scene_query_text(scene: SceneRecord) -> str:
    ordered_parts = [
        *scene.context.subject,
        *scene.context.action,
        *scene.context.location,
        *scene.context.objects,
        *scene.context.keywords,
        scene.english_text,
    ]
    unique: list[str] = []
    seen: set[str] = set()
    for raw in ordered_parts:
        value = " ".join(str(raw).split()).strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            unique.append(value)
    return " ".join(unique)


def exact_phrases(scene: SceneRecord) -> tuple[str, ...]:
    candidates = [
        *scene.context.subject,
        *scene.context.action,
        *scene.context.location,
        *scene.context.objects,
        *scene.context.keywords,
    ]
    result: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        value = " ".join(str(raw).split()).strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)


def _overlap_seconds(start: float, end: float, other_start: float, other_end: float) -> float:
    return max(0.0, min(end, other_end) - max(start, other_start))


def _fallback_shots(analysis: CandidateAnalysis) -> tuple[ShotSegment, ...]:
    if analysis.shots:
        return analysis.shots
    duration = analysis.metadata.duration
    if duration <= 0 and analysis.transcript:
        duration = max(item.end for item in analysis.transcript)
    if duration <= 0:
        return ()
    return (ShotSegment(index=1, start=0.0, end=duration),)


def analysis_to_units(
    analysis: CandidateAnalysis,
    *,
    metadata_text: str = "",
) -> tuple[RetrievalUnit, ...]:
    units: list[RetrievalUnit] = []
    for shot in _fallback_shots(analysis):
        overlapping = [
            segment
            for segment in analysis.transcript
            if segment.end > shot.start and segment.start < shot.end
        ]
        text = " ".join(segment.text.strip() for segment in overlapping if segment.text.strip())
        covered = sum(
            _overlap_seconds(shot.start, shot.end, segment.start, segment.end)
            for segment in overlapping
        )
        coverage = min(1.0, covered / shot.duration) if shot.duration > 0 else 0.0
        units.append(
            RetrievalUnit(
                unit_id=f"{analysis.fingerprint.sha256[:16]}:shot:{shot.index:05d}",
                source_path=analysis.source_path,
                start=shot.start,
                end=shot.end,
                transcript_text=text,
                metadata_text=metadata_text,
                transcript_coverage=round(coverage, 6),
            )
        )
    return tuple(units)
