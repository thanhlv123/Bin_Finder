from bin_finder.diversity import (
    DiversityCandidate,
    DiversityPolicy,
    SourceDiversitySelector,
    suppress_scene_duplicates,
)


def c(
    candidate_id,
    scene_id,
    scene_order,
    source_id,
    start,
    end,
    score,
    *,
    duplicate_group="",
):
    return DiversityCandidate(
        candidate_id=candidate_id,
        scene_id=scene_id,
        scene_order=scene_order,
        source_id=source_id,
        start=start,
        end=end,
        score=score,
        duplicate_group=duplicate_group,
    )


def test_default_rotation_allows_a_b_a_but_not_a_a():
    selector = SourceDiversitySelector()
    result = selector.select(
        [
            c("s1a", "s1", 1, "A", 0, 5, 0.95),
            c("s2a", "s2", 2, "A", 10, 15, 0.96),
            c("s2b", "s2", 2, "B", 0, 5, 0.90),
            c("s3a", "s3", 3, "A", 20, 25, 0.94),
        ]
    )

    assert [item.source_id for item in result.selected] == ["A", "B", "A"]
    assert result.decisions[1].reason == "diversity-alternative"


def test_same_source_nonadjacent_overlap_is_rejected():
    selector = SourceDiversitySelector()
    result = selector.select(
        [
            c("s1a", "s1", 1, "A", 0, 5, 0.95),
            c("s2b", "s2", 2, "B", 0, 5, 0.90),
            c("s3a-overlap", "s3", 3, "A", 4, 9, 0.96),
            c("s3a-clean", "s3", 3, "A", 10, 15, 0.91),
        ]
    )

    assert result.decisions[2].candidate.candidate_id == "s3a-clean"


def test_touching_ranges_do_not_count_as_overlap():
    selector = SourceDiversitySelector()
    result = selector.select(
        [
            c("s1a", "s1", 1, "A", 0, 5, 0.95),
            c("s2b", "s2", 2, "B", 0, 5, 0.90),
            c("s3a", "s3", 3, "A", 5, 10, 0.93),
        ]
    )

    assert result.decisions[2].candidate.candidate_id == "s3a"


def test_score_guardrail_marks_low_context_instead_of_poor_alternative():
    selector = SourceDiversitySelector(
        DiversityPolicy(max_score_drop=0.18)
    )
    result = selector.select(
        [
            c("s1a", "s1", 1, "A", 0, 5, 0.95),
            c("s2a", "s2", 2, "A", 10, 15, 0.96),
            c("s2b", "s2", 2, "B", 0, 5, 0.50),
        ]
    )

    assert result.decisions[1].candidate is None
    assert result.decisions[1].reason == "low-context-match"


def test_duplicate_group_prevents_same_visual_reuse_across_sources():
    selector = SourceDiversitySelector()
    result = selector.select(
        [
            c("s1a", "s1", 1, "A", 0, 5, 0.95, duplicate_group="visual-1"),
            c("s2b-dup", "s2", 2, "B", 0, 5, 0.94, duplicate_group="visual-1"),
            c("s2c", "s2", 2, "C", 0, 5, 0.90, duplicate_group="visual-2"),
        ]
    )

    assert result.decisions[1].candidate.candidate_id == "s2c"


def test_same_scene_near_duplicate_ranges_are_suppressed():
    kept = suppress_scene_duplicates(
        [
            c("high", "s1", 1, "A", 0, 5, 0.95),
            c("low", "s1", 1, "A", 0.2, 5.2, 0.90),
            c("other", "s1", 1, "B", 0, 5, 0.80),
        ],
        iou_threshold=0.8,
    )

    assert [item.candidate_id for item in kept] == ["high", "other"]


def test_expected_scene_without_candidates_is_unresolved():
    result = SourceDiversitySelector().select(
        [c("s1a", "s1", 1, "A", 0, 5, 0.95)],
        expected_scenes=[(1, "s1"), (2, "s2")],
    )

    assert result.unresolved_scene_ids == ("s2",)
    assert result.decisions[1].reason == "no-candidates"


def test_cooldown_two_blocks_a_b_a():
    selector = SourceDiversitySelector(
        DiversityPolicy(source_cooldown=2, max_score_drop=0.2)
    )
    result = selector.select(
        [
            c("s1a", "s1", 1, "A", 0, 5, 0.95),
            c("s2b", "s2", 2, "B", 0, 5, 0.94),
            c("s3a", "s3", 3, "A", 10, 15, 0.93),
            c("s3c", "s3", 3, "C", 0, 5, 0.90),
        ]
    )

    assert [item.source_id for item in result.selected] == ["A", "B", "C"]


def test_invalid_ranges_become_diversity_conflict():
    result = SourceDiversitySelector().select(
        [c("bad", "s1", 1, "A", 5, 5, 0.9)]
    )
    assert result.decisions[0].candidate is None
    assert result.decisions[0].reason == "diversity-conflict"


def test_selection_is_deterministic_on_equal_scores():
    selector = SourceDiversitySelector()
    candidates = [
        c("z", "s1", 1, "B", 0, 5, 0.9),
        c("a", "s1", 1, "A", 0, 5, 0.9),
    ]
    first = selector.select(candidates)
    second = selector.select(reversed(candidates))

    assert first.selected[0].candidate_id == second.selected[0].candidate_id
