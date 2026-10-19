import pytest

from bin_finder.clips.models import ClipPolicy
from bin_finder.clips.planner import SmartClipPlanner
from bin_finder.retrieval.models import RankedSegment, RetrievalScores, RetrievalUnit
from bin_finder.verification.models import VerifiedSegment


def verified(unit_id, start, end, score=0.9):
    ranked = RankedSegment(
        unit=RetrievalUnit(unit_id, "D:/clips/source.mp4", start, end, unit_id),
        scores=RetrievalScores(0.8, 0.5, 0.7, None, score),
    )
    return VerifiedSegment(
        segment=ranked,
        verification=None,
        verification_score=None,
        final_score=score,
        status="verified",
    )


def test_in_range_shot_is_kept_whole():
    proposal = SmartClipPlanner().propose(verified("a", 10.0, 16.0))
    assert proposal.accepted is True
    assert proposal.reason == "whole-shot"
    assert proposal.start == 10.0
    assert proposal.end == 16.0
    assert proposal.duration == 6.0


def test_long_shot_uses_five_second_center_window():
    proposal = SmartClipPlanner().propose(verified("a", 0.0, 12.0))
    assert proposal.reason == "target-window"
    assert proposal.start == 3.5
    assert proposal.end == 8.5
    assert proposal.duration == 5.0


def test_anchor_time_is_clamped_inside_shot():
    proposal = SmartClipPlanner().propose(
        verified("a", 10.0, 22.0),
        anchor_time=10.5,
    )
    assert proposal.start == 10.0
    assert proposal.end == 15.0
    assert proposal.anchor_time == 10.5


def test_short_shot_is_rejected_by_default():
    proposal = SmartClipPlanner().propose(verified("a", 0.0, 3.0))
    assert proposal.accepted is False
    assert proposal.reason == "shot-too-short"


def test_short_shot_can_be_explicitly_allowed():
    planner = SmartClipPlanner(
        ClipPolicy(
            target_duration=5.0,
            min_duration=3.5,
            max_duration=7.0,
            allow_short_shots=True,
        )
    )
    proposal = planner.propose(verified("a", 0.0, 3.0))
    assert proposal.accepted is True
    assert proposal.reason == "short-shot-allowed"


def test_propose_many_filters_rejected_and_applies_limit():
    planner = SmartClipPlanner()
    proposals = planner.propose_many(
        [
            verified("short", 0, 2),
            verified("good1", 2, 7),
            verified("good2", 7, 12),
        ],
        limit=1,
    )
    assert [item.unit_id for item in proposals] == ["good1"]


def test_policy_rejects_target_outside_bounds():
    with pytest.raises(ValueError):
        SmartClipPlanner(
            ClipPolicy(target_duration=8.0, min_duration=3.5, max_duration=7.0)
        )
