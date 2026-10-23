"""ZB-02 offline-only contract checks. Synthetic scripts, no Z5 or Cuba data."""
from copy import deepcopy
from dataclasses import replace

import pytest

from bin_finder.models import SceneContext, SceneRecord
from bin_finder.visual_planning import VisualPlanningError, parse_visual_story_plan


def scenes():
    texts = (
        "Fishing boats return to the harbor before sunrise.",
        "Workers unload baskets and repair their fishing nets.",
        "But everyday life behind the harbor changes sharply.",
        "The cost of living rises for local households.",
    )
    return tuple(
        SceneRecord(scene_id=f"scene_{i:03}", order=i, english_text=txt,
                    context=SceneContext(keywords=("synthetic harbor",)))
        for i, txt in enumerate(texts, 1)
    )


def search_shot(sid, bid, covered, goal, queries, evidence="contextual"):
    return {
        "shot_id": sid, "block_id": bid, "scene_ids": covered,
        "strategy": "search", "evidence_type": evidence,
        "visual_goal": goal, "queries": queries, "hold_from_shot_id": None,
    }


def base_plan():
    return {
        "format": "bin_finder_visual_plan_v1",
        "plan_id": "offline_test_visual_story",
        "blocks": [
            {
                "block_id": "b1", "scene_ids": ["scene_001", "scene_002"],
                "role": "establish", "summary": "Harbor and local work",
                "visual_purpose": "Establish the physical setting and work",
            },
            {
                "block_id": "b2", "scene_ids": ["scene_003", "scene_004"],
                "role": "contrast", "summary": "Transition into pressures on households",
                "visual_purpose": "Show transition to daily-life context",
            },
        ],
        "shots": [
            search_shot(
                "s1", "b1", ["scene_001", "scene_002"],
                "Boats at the working harbor",
                ["fishing boats early morning harbor"],
            ),
            {
                "shot_id": "s2", "block_id": "b2", "scene_ids": ["scene_003"],
                "strategy": "transition", "evidence_type": "not_applicable",
                "visual_goal": "Change from idyllic harbor to local daily life",
                "queries": [], "hold_from_shot_id": None,
            },
            search_shot(
                "s3", "b2", ["scene_003", "scene_004"],
                "A local market during ordinary daily life",
                ["residential market stalls locals"], "contextual",
            ),
            {
                "shot_id": "s4", "block_id": "b2", "scene_ids": ["scene_004"],
                "strategy": "hold", "evidence_type": "not_applicable",
                "visual_goal": "Continue existing market footage over the claim",
                "queries": [], "hold_from_shot_id": "s3",
            },
        ],
    }


def test_one_shot_can_cover_two_scenes_and_transition_needs_no_search():
    source = scenes()
    snapshot = deepcopy(source)
    plan = parse_visual_story_plan(base_plan(), source)
    assert source == snapshot
    assert plan.shots[0].scene_ids == ("scene_001", "scene_002")
    assert plan.shots[1].strategy == "transition"
    assert plan.shots[3].strategy == "hold"
    assert [r.shot_id for r in plan.search_requests()] == ["s1", "s3"]
    assert plan.shots[3].hold_from_shot_id == "s3"


def test_two_shots_can_cover_one_narration_scene_with_separate_subjects():
    draft = base_plan()
    draft["shots"].insert(1, search_shot(
        "s1b", "b1", ["scene_002"], "A worker repairs fishing nets",
        ["fisherman repairing fishing nets"], "direct",
    ))
    plan = parse_visual_story_plan(draft, scenes())
    assert len(plan.shots) == 5
    assert plan.shots[0].scene_ids == ("scene_001", "scene_002")
    assert plan.shots[1].scene_ids == ("scene_002",)
    assert len(plan.search_requests()) == 3


def test_graphic_is_a_separate_planned_action_not_provider_search():
    draft = base_plan()
    draft["shots"][3] = {
        "shot_id": "s4", "block_id": "b2", "scene_ids": ["scene_004"],
        "strategy": "graphic", "evidence_type": "not_applicable",
        "visual_goal": "Graphic placeholder: research price numbers separately",
        "queries": [], "hold_from_shot_id": None,
    }
    plan = parse_visual_story_plan(draft, scenes())
    assert plan.shots[3].strategy == "graphic"
    assert len(plan.search_requests()) == 2


def test_mapping_round_trip_and_stable_identity():
    original = parse_visual_story_plan(base_plan(), scenes())
    replay = parse_visual_story_plan(original.to_mapping(), scenes())
    assert replay == original
    assert replay.to_mapping() == original.to_mapping()
    assert all(isinstance(x.queries, tuple) for x in replay.shots)


@pytest.mark.parametrize("mutation, reason", [
    (lambda d: d.update(format="unknown"), "invalid-format"),
    (lambda d: d["blocks"][0].update(scene_ids=["scene_002", "scene_001"]),
     "block-scene-partition"),
    (lambda d: d["blocks"][1].update(scene_ids=["scene_004"]), "block-scene-partition"),
    (lambda d: d["shots"][0].update(scene_ids=["scene_001", "scene_003"]),
     "invalid-shot-order-or-span"),
    (lambda d: d["shots"][1].update(queries=["invalid search"]),
     "invalid-nonsearch-shot"),
    (lambda d: d["shots"][3].update(hold_from_shot_id="missing"),
     "invalid-hold-shot"),
    (lambda d: d["shots"][0].update(queries=[]), "invalid-search-shot"),
    (lambda d: d["shots"][0].update(queries=["one", "two", "three", "four"]),
     "invalid-shot-queries"),
    (lambda d: d["shots"][2].update(shot_id="s1"), "duplicate-shot-id"),
    (lambda d: d["shots"][2].update(block_id="missing"), "unknown-shot-block"),
    (lambda d: d["shots"][0].update(evidence_type="invented"), "invalid-strategy-or-evidence"),
    (lambda d: d["shots"][0].update(visual_goal=" " * 10), "invalid-visual-goal"),
])
def test_invalid_plan_fails_closed(mutation, reason):
    draft = base_plan()
    mutation(draft)
    with pytest.raises(VisualPlanningError, match=reason):
        parse_visual_story_plan(draft, scenes())


def test_search_queries_bound_and_do_not_execute_input():
    draft = base_plan()
    draft["shots"][0]["queries"] = ["${whoami}; rm -rf /"]
    plan = parse_visual_story_plan(draft, scenes())
    assert plan.search_requests()[0].queries == ("${whoami}; rm -rf /",)
    with pytest.raises(VisualPlanningError, match="invalid-shot-query"):
        draft["shots"][0]["queries"] = ["x" * 161]
        parse_visual_story_plan(draft, scenes())


def test_scene_objects_unchanged_after_error():
    original = scenes()
    copy = tuple(replace(s) for s in original)
    invalid = base_plan()
    invalid["shots"][3]["hold_from_shot_id"] = "s1"
    with pytest.raises(VisualPlanningError):
        parse_visual_story_plan(invalid, original)
    assert original == copy


def test_no_visual_shot_left_uncovered():
    draft = base_plan()
    draft["shots"][0]["scene_ids"] = ["scene_001"]
    # Scene 002 is no longer covered; no automatic fabricated footage.
    with pytest.raises(VisualPlanningError, match="uncovered-narration-scenes"):
        parse_visual_story_plan(draft, scenes())


def test_scenes_must_keep_stable_order():
    original = scenes()
    shifted = (replace(original[0], order=4),) + original[1:]
    with pytest.raises(VisualPlanningError, match="unordered-scenes"):
        parse_visual_story_plan(base_plan(), shifted)


def test_semantic_truth_is_not_implied_by_valid_structure():
    draft = base_plan()
    draft["shots"][0]["visual_goal"] = "An unverifiable and misleading claim"
    # Schema accepts bounded text: a later editor/vision check must judge truth.
    assert parse_visual_story_plan(draft, scenes()).shots[0].visual_goal == (
        "An unverifiable and misleading claim"
    )



def test_first_shot_needs_an_actual_search_or_graphic_visual():
    draft = base_plan()
    draft["shots"][0] = {
        "shot_id": "s1", "block_id": "b1",
        "scene_ids": ["scene_001", "scene_002"],
        "strategy": "transition", "evidence_type": "not_applicable",
        "visual_goal": "Transition without a prior visible image",
        "queries": [], "hold_from_shot_id": None,
    }
    with pytest.raises(VisualPlanningError, match="missing-opening-visual"):
        parse_visual_story_plan(draft, scenes())
