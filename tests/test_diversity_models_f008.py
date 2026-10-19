import pytest

from bin_finder.diversity import DiversityCandidate, DiversityPolicy
from bin_finder.models import CandidateRecord


def test_candidate_record_conversion_uses_proposed_range():
    candidate = CandidateRecord(
        candidate_id="cand",
        scene_id="scene_001",
        provider="local",
        source_id="local:abc",
        title="clip",
        duration=20.0,
        score=0.91,
        proposed_start=10.0,
        proposed_end=15.0,
    )
    converted = DiversityCandidate.from_candidate_record(
        candidate,
        scene_order=1,
    )

    assert converted.start == 10.0
    assert converted.end == 15.0
    assert converted.duration == 5.0
    assert converted.score == 0.91


def test_candidate_record_conversion_falls_back_to_duration():
    candidate = CandidateRecord(
        candidate_id="cand",
        scene_id="scene_001",
        provider="local",
        source_id="local:abc",
        title="clip",
        duration=6.0,
        score=1.2,
    )
    converted = DiversityCandidate.from_candidate_record(
        candidate,
        scene_order=1,
    )

    assert converted.start == 0.0
    assert converted.end == 6.0
    assert converted.score == 1.0


@pytest.mark.parametrize(
    "policy",
    [
        DiversityPolicy(source_cooldown=-1),
        DiversityPolicy(max_score_drop=1.1),
        DiversityPolicy(min_score=-0.1),
        DiversityPolicy(overlap_tolerance=-0.1),
        DiversityPolicy(duplicate_iou_threshold=1.1),
    ],
)
def test_invalid_policy_is_rejected(policy):
    with pytest.raises(ValueError):
        policy.validate()
