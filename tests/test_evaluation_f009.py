from pathlib import Path

import pytest

from bin_finder.evaluation import ABComparison, ReviewDecision, ReviewStore


def test_review_store_round_trip_and_latest_decision_wins(tmp_path: Path):
    store = ReviewStore(tmp_path / "review.json")
    store.record_decision(
        ReviewDecision("scene_001", "cand_1", "waitlist", score=0.7)
    )
    store.record_decision(
        ReviewDecision("scene_001", "cand_1", "accepted", score=0.9)
    )

    decisions = store.decisions()
    assert len(decisions) == 1
    assert decisions[0].decision == "accepted"
    assert decisions[0].score == 0.9


def test_review_store_records_ab_comparisons_and_summary(tmp_path: Path):
    store = ReviewStore(tmp_path / "review.json")
    store.record_decision(ReviewDecision("s1", "a", "accepted"))
    store.record_decision(ReviewDecision("s1", "b", "rejected"))
    store.record_decision(ReviewDecision("s2", "c", "waitlist"))
    store.add_comparison(ABComparison("s1", "a", "b", "a"))
    store.add_comparison(ABComparison("s1", "a", "b", "b"))

    summary = store.summary()
    assert summary.accepted == 1
    assert summary.rejected == 1
    assert summary.waitlist == 1
    assert summary.comparisons == 2
    assert summary.candidate_wins == {"a": 1, "b": 1}


def test_invalid_decision_is_rejected(tmp_path: Path):
    store = ReviewStore(tmp_path / "review.json")
    with pytest.raises(ValueError):
        store.record_decision(ReviewDecision("s1", "a", "maybe"))


def test_ab_winner_must_be_one_of_pair(tmp_path: Path):
    store = ReviewStore(tmp_path / "review.json")
    with pytest.raises(ValueError):
        store.add_comparison(ABComparison("s1", "a", "b", "c"))
