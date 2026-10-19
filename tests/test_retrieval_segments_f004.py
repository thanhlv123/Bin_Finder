from bin_finder.analysis.models import (
    CandidateAnalysis,
    MediaFingerprint,
    MediaMetadata,
    ShotSegment,
    TranscriptSegment,
)
from bin_finder.demo_data import demo_scenes
from bin_finder.retrieval.segments import (
    analysis_to_units,
    build_scene_query_text,
    exact_phrases,
)


def analysis_fixture():
    return CandidateAnalysis(
        source_path="D:/clips/cuba.mp4",
        analyzer_version="f003-v1",
        fingerprint=MediaFingerprint("a" * 64, 100, 1),
        metadata=MediaMetadata(duration=10.0),
        transcript=(
            TranscriptSegment(1.0, 2.5, "family walking through airport"),
            TranscriptSegment(5.0, 7.0, "mechanic repairing classic Chevrolet"),
        ),
        shots=(
            ShotSegment(1, 0.0, 4.0),
            ShotSegment(2, 4.0, 10.0),
        ),
    )


def test_analysis_to_units_aligns_transcript_to_shots():
    units = analysis_to_units(analysis_fixture(), metadata_text="Cuba documentary")

    assert len(units) == 2
    assert "airport" in units[0].transcript_text
    assert "mechanic" not in units[0].transcript_text
    assert "mechanic" in units[1].transcript_text
    assert units[0].metadata_text == "Cuba documentary"
    assert units[0].start == 0.0
    assert units[1].end == 10.0
    assert 0 < units[0].transcript_coverage < 1


def test_analysis_to_units_falls_back_to_media_duration_without_shots():
    source = analysis_fixture()
    analysis = CandidateAnalysis(
        source_path=source.source_path,
        analyzer_version=source.analyzer_version,
        fingerprint=source.fingerprint,
        metadata=source.metadata,
        transcript=source.transcript,
        shots=(),
    )
    units = analysis_to_units(analysis)
    assert len(units) == 1
    assert units[0].start == 0.0
    assert units[0].end == 10.0


def test_scene_query_prefers_structured_context_and_dedupes():
    scene = demo_scenes()[0]
    query = build_scene_query_text(scene)
    phrases = exact_phrases(scene)

    assert "Havana mechanic" in query
    assert "classic Chevrolet" in query
    assert len(phrases) == len(set(item.casefold() for item in phrases))
