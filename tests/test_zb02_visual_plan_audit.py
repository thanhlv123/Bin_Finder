"""ZB-02B generic read-only audit flags, synthetic genre fixtures only."""
from dataclasses import replace

import pytest

from bin_finder.visual_director_smoke import editorial_example, synthetic_scenes
from bin_finder.visual_plan_audit import audit_visual_story_plan
from bin_finder.visual_planning import VisualPlanningError, parse_visual_story_plan


def test_travel_transition_only_scene_is_pending_scheduling():
    scenes = synthetic_scenes("travel")
    plan = parse_visual_story_plan(editorial_example("travel"), scenes)
    original = plan.to_mapping()
    audit = audit_visual_story_plan(plan, scenes)
    assert audit.scene_count == 4
    assert audit.block_count == 2
    assert audit.shot_count == 3
    assert audit.search_count == 2
    assert audit.transition_count == 1
    assert audit.hold_count == 0
    assert audit.graphic_count == 0
    assert audit.multi_scene_shot_count == 2
    assert [f.code for f in audit.flags] == [
        "transition-only-visual-coverage-unresolved"
    ]
    assert audit.flags[0].scene_ids == ("scene_003",)
    assert plan.to_mapping() == original


def test_history_hold_means_no_new_search_and_no_unresolved_transition():
    scenes = synthetic_scenes("history")
    plan = parse_visual_story_plan(editorial_example("history"), scenes)
    audit = audit_visual_story_plan(plan, scenes)
    assert audit.search_count == 2
    assert audit.hold_count == 1
    assert audit.transition_count == 0
    assert audit.flags == ()
    assert audit.scenes_with_multiple_shots == 0


def test_economy_proper_graphic_not_stock_search():
    scenes = synthetic_scenes("economy")
    plan = parse_visual_story_plan(editorial_example("economy"), scenes)
    audit = audit_visual_story_plan(plan, scenes)
    assert audit.search_count == 1
    assert audit.graphic_count == 1
    assert audit.hold_count == 1
    assert audit.flags == ()


def test_stock_chart_warning_only_and_no_auto_rewrite():
    scenes = synthetic_scenes("economy")
    draft = editorial_example("economy")
    draft["shots"][2] = {
        "shot_id": "s3", "block_id": "b2", "scene_ids": ["scene_004"],
        "strategy": "search", "evidence_type": "direct",
        "visual_goal": "find a chart showing verified salary and price data",
        "queries": ["economic chart with salary graph"],
        "hold_from_shot_id": None,
    }
    plan = parse_visual_story_plan(draft, scenes)
    audit = audit_visual_story_plan(plan, scenes)
    assert len(audit.flags) == 1
    assert audit.flags[0].code == "graphic-like-content-routed-to-stock-search"
    assert audit.flags[0].shot_id == "s3"
    assert audit.search_count == 2
    assert len(plan.search_requests()) == 2
    assert plan.shots[2].strategy == "search"  # warning does not mutate
    assert audit.to_mapping()["flags"][0]["scene_ids"] == ["scene_004"]


def test_generic_non_chart_search_not_flagged():
    scenes = synthetic_scenes("history")
    draft = editorial_example("history")
    draft["shots"][2]["queries"] = ["documentary historic map of bridge trade routes"]
    plan = parse_visual_story_plan(draft, scenes)
    assert audit_visual_story_plan(plan, scenes).flags == ()


def test_multi_shots_on_one_scene_counted_not_penalized():
    scenes = synthetic_scenes("travel")
    draft = editorial_example("travel")
    draft["shots"].insert(1, {
        "shot_id": "s1b", "block_id": "b1", "scene_ids": ["scene_002"],
        "strategy": "search", "evidence_type": "direct",
        "visual_goal": "Fishermen repair a net", "queries": ["fishermen mending net"],
        "hold_from_shot_id": None,
    })
    plan = parse_visual_story_plan(draft, scenes)
    audit = audit_visual_story_plan(plan, scenes)
    assert audit.scenes_with_multiple_shots == 1
    assert audit.search_count == 3
    assert all(flag.code != "excessive-shots" for flag in audit.flags)


def test_malformed_or_forged_plan_does_not_produce_audit():
    scenes = synthetic_scenes("travel")
    plan = parse_visual_story_plan(editorial_example("travel"), scenes)
    with pytest.raises(VisualPlanningError, match="invalid-audit-plan"):
        audit_visual_story_plan({}, scenes)
    forged = replace(plan, blocks=())
    with pytest.raises(VisualPlanningError, match="invalid-blocks"):
        audit_visual_story_plan(forged, scenes)


def test_audit_mapping_has_only_ids_codes_and_counts_not_private_narration():
    scenes = synthetic_scenes("travel")
    plan = parse_visual_story_plan(editorial_example("travel"), scenes)
    output = audit_visual_story_plan(plan, scenes).to_mapping()
    assert output["flags"][0] == {
        "code": "transition-only-visual-coverage-unresolved",
        "shot_id": "s2",
        "scene_ids": ["scene_003"],
    }
    assert "Fishing boats return" not in repr(output)
    assert "visual_goal" not in repr(output)
