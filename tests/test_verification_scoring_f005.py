from bin_finder.verification.models import VerificationDimensions
from bin_finder.verification.scoring import VerificationWeights, verification_score


def test_verification_score_renormalizes_missing_dimensions():
    score = verification_score(
        VerificationDimensions(
            subject_match=1.0,
            action_match=0.5,
            location_match=None,
            context_conflict=0.0,
        ),
        weights=VerificationWeights(
            subject_match=1.0,
            action_match=1.0,
            location_match=1.0,
            object_match=0.0,
            time_match=0.0,
            visual_quality=0.0,
            context_conflict_penalty=0.5,
        ),
    )
    assert score == 0.75


def test_context_conflict_penalizes_candidate():
    base = VerificationDimensions(
        subject_match=1.0,
        action_match=1.0,
        context_conflict=0.0,
    )
    conflict = VerificationDimensions(
        subject_match=1.0,
        action_match=1.0,
        context_conflict=1.0,
    )
    assert verification_score(conflict) < verification_score(base)


def test_scores_are_clamped_to_zero_one():
    score = verification_score(
        VerificationDimensions(
            subject_match=2.0,
            action_match=-1.0,
            context_conflict=-2.0,
        )
    )
    assert 0.0 <= score <= 1.0
