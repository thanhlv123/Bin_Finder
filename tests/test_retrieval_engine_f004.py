import pytest

from bin_finder.analysis.models import (
    CandidateAnalysis,
    MediaFingerprint,
    MediaMetadata,
    ShotSegment,
    TranscriptSegment,
)
from bin_finder.demo_data import demo_scenes
from bin_finder.retrieval.engine import HybridRetrievalEngine, ScoreWeights
from bin_finder.retrieval.models import RetrievalUnit


class FixedTextProvider:
    name = "fixed-text"

    def __init__(self, values):
        self.values = list(values)

    def score(self, query, texts):
        return list(self.values)


class FixedVisualProvider:
    name = "fixed-visual"

    def __init__(self, values):
        self.values = list(values)

    def score(self, query, units):
        return list(self.values)


def analysis_fixture():
    return CandidateAnalysis(
        source_path="D:/clips/cuba.mp4",
        analyzer_version="f003-v1",
        fingerprint=MediaFingerprint("b" * 64, 100, 1),
        metadata=MediaMetadata(duration=10.0),
        transcript=(
            TranscriptSegment(0.5, 3.0, "family waiting at airport terminal"),
            TranscriptSegment(5.0, 8.0, "Havana mechanic repairs classic Chevrolet"),
        ),
        shots=(
            ShotSegment(1, 0.0, 4.0),
            ShotSegment(2, 4.0, 10.0),
        ),
    )


def test_default_engine_ranks_matching_shot_first():
    engine = HybridRetrievalEngine()
    ranked = engine.rank_analysis(
        demo_scenes()[0],
        analysis_fixture(),
        metadata_text="Cuba documentary footage",
    )

    assert len(ranked) == 2
    assert ranked[0].unit.start == 4.0
    assert ranked[0].scores.bm25 == 1.0
    assert ranked[0].scores.final > ranked[1].scores.final
    assert ranked[0].scores.visual_similarity is None


def test_visual_provider_can_rerank_when_given_high_weight():
    units = [
        RetrievalUnit("a", "clip.mp4", 0, 5, "unrelated words"),
        RetrievalUnit("b", "clip.mp4", 5, 10, "Havana mechanic classic Chevrolet"),
    ]
    engine = HybridRetrievalEngine(
        text_provider=FixedTextProvider([0.0, 0.0]),
        visual_provider=FixedVisualProvider([1.0, 0.0]),
        weights=ScoreWeights(
            bm25=0.0,
            exact=0.0,
            text_similarity=0.0,
            visual_similarity=1.0,
        ),
    )

    ranked = engine.rank_units(demo_scenes()[0], units)

    assert ranked[0].unit.unit_id == "a"
    assert ranked[0].scores.visual_similarity == 1.0
    assert ranked[0].scores.final == 1.0


def test_missing_visual_signal_is_removed_from_weight_denominator():
    units = [RetrievalUnit("a", "clip.mp4", 0, 5, "Havana mechanic")]
    engine = HybridRetrievalEngine(
        text_provider=FixedTextProvider([1.0]),
        visual_provider=FixedVisualProvider([None]),
        weights=ScoreWeights(
            bm25=0.0,
            exact=0.0,
            text_similarity=0.3,
            visual_similarity=0.7,
        ),
    )
    ranked = engine.rank_units(demo_scenes()[0], units)
    assert ranked[0].scores.final == 1.0


def test_provider_score_count_must_match_unit_count():
    units = [RetrievalUnit("a", "clip.mp4", 0, 5, "Havana mechanic")]
    engine = HybridRetrievalEngine(
        text_provider=FixedTextProvider([]),
    )
    with pytest.raises(ValueError, match="Text similarity provider"):
        engine.rank_units(demo_scenes()[0], units)


def test_weights_reject_all_zero():
    with pytest.raises(ValueError):
        HybridRetrievalEngine(weights=ScoreWeights(0.0, 0.0, 0.0, 0.0))


def test_limit_is_applied_after_ranking():
    units = [
        RetrievalUnit("a", "clip.mp4", 0, 5, "airport"),
        RetrievalUnit("b", "clip.mp4", 5, 10, "Havana mechanic classic Chevrolet"),
    ]
    ranked = HybridRetrievalEngine().rank_units(
        demo_scenes()[0],
        units,
        limit=1,
    )
    assert len(ranked) == 1
    assert ranked[0].unit.unit_id == "b"
