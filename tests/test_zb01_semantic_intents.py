"""ZB-01 offline experimental tests: no model, network or provider calls."""
from dataclasses import replace

import pytest

from bin_finder.models import SceneContext, SceneRecord
from bin_finder.search.query_builder import build_scene_queries
from bin_finder.search.semantic_intents import (
    InvalidIntent, SceneSearchIntent, StoryCapsule, proposed_queries_for_scene,
)

SCRIPT = "At ten at night, office lights still glow in Lujiazui, Shanghai."


def sample_scene():
    return SceneRecord(
        scene_id="scene_001", order=1, english_text=SCRIPT,
        target_duration=5.0,
        context=SceneContext(keywords=("office lights",)),
    )


def proposed():
    return {
        "scene_id": "scene_001",
        "narration_text": SCRIPT,
        "visual_goal": "Office towers with lights after dark",
        "required_entities": ["Lujiazui"],
        "must_show": ["illuminated office towers", "night"],
        "must_not_show": ["daytime skyline"],
        "queries": [
            "Lujiazui office towers at night",
            "Lujiazui illuminated skyline",
        ],
        "uncertainty": "Lights do not prove that workers are present",
        "provenance": "editor_review",
    }


def test_valid_plan_and_opt_in_adapter_keep_scene_identity():
    scene = sample_scene()
    before = build_scene_queries(scene)
    result = proposed_queries_for_scene(scene, proposed(), full_script=SCRIPT)
    assert result == proposed()["queries"]
    assert build_scene_queries(scene) == before
    assert scene.scene_id == "scene_001"
    assert scene.target_duration == 5.0


def test_absent_plan_identical_to_legacy():
    scene = sample_scene()
    assert proposed_queries_for_scene(
        scene, None, full_script=SCRIPT,
    ) == build_scene_queries(scene)


@pytest.mark.parametrize("change", [
    {"scene_id": "other"},
    {"narration_text": "other"},
    {"queries": ["Shanghai at night"]},
    {"queries": ["Lujiazui" for _ in range(4)]},
    {"queries": ["Lujiazui", "lujiazui"]},
    {"required_entities": ["Tokyo"]},
    {"provenance": "random-ai"},
])
def test_invalid_plan_never_replaces_legacy(change):
    scene = sample_scene()
    bad = {**proposed(), **change}
    assert proposed_queries_for_scene(
        scene, bad, full_script=SCRIPT,
    ) == build_scene_queries(scene)


def test_output_bound_and_story_capsule():
    scene = sample_scene()
    assert proposed_queries_for_scene(
        scene, proposed(), full_script=SCRIPT, max_queries=1,
    ) == [proposed()["queries"][0]]
    capsule = StoryCapsule.from_mapping({
        "summary": "Office lights remain on",
        "central_message": "Night activity",
        "arc": "",
    })
    assert capsule.central_message == "Night activity"
    with pytest.raises(InvalidIntent):
        StoryCapsule.from_mapping({
            "summary": "A" * 501,
            "central_message": "Night activity",
            "arc": "",
        })


def test_no_side_effects_or_scene_mutation():
    scene = sample_scene()
    copy = replace(scene)
    _ = proposed_queries_for_scene(scene, proposed(), full_script=SCRIPT)
    assert scene == copy
