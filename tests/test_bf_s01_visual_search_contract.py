"""BF-S01 isolated contract tests: invented narration, no external Z5 code/data."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from bin_finder.models import SceneRecord
from bin_finder.search.visual_search_contract import (
    FORMAT, SearchPlanError, parse_semantic_search_plan, script_digest,
)


STORIES = {
    "travel": (
        "Fishing boats arrive at the harbor before sunrise.",
        "Workers unload fish and repair nets on the pier.",
        "But behind the postcard view life is more complicated.",
        "Residents buy food at the morning market.",
    ),
    "history": (
        "A stone bridge connected the valley.",
        "Merchants carried baskets and cloth across it.",
        "Over centuries the routes of trade changed.",
        "The surviving bridge remains today.",
    ),
    "economy": (
        "Office towers glow after dark.",
        "Commuters crowd trains in the evening.",
        "City lights cannot prove real wages.",
        "Reliable charts need verified wage and price figures.",
    ),
}


def scenes(genre="travel"):
    return tuple(
        SceneRecord(scene_id=f"scene_{index:03d}",
                    order=index, english_text=text)
        for index, text in enumerate(STORIES[genre], 1)
    )


def slot(slot_id, beat_id, scene_ids, source_text, *, action="search",
         reuse=None, goal="Visible scene relevant to the story"):
    is_search = action == "search"
    return {
        "slot_id": slot_id, "beat_id": beat_id,
        "scene_ids": list(scene_ids), "role": "develop",
        "action": action,
        "evidence_type": "contextual" if is_search else "not_applicable",
        "entity_policy": "contextual" if is_search else "unspecified",
        "source_text": source_text,
        "visual_brief": goal,
        "must_show": ["visible relevant subject"] if is_search else [],
        "must_not_show": ["unrelated talking head"] if is_search else [],
        "required_entities": [],
        "queries": [
            {"axis": "subject", "text": "coastal harbor fishing boats"},
            {"axis": "moment", "text": "working pier in early morning"},
            {"axis": "action", "text": "workers unloading catch at port"},
        ] if is_search else [],
        "reuse_from_slot_id": reuse,
        "uncertainty": "No direct footage proof." if action == "no_match" else "",
    }


def example(genre="travel"):
    source = scenes(genre)
    beat1 = {
        "beat_id": "b1",
        "scene_ids": ["scene_001", "scene_002"],
        "meaning": "Physical setting and human activity",
        "anchor_text": source[0].english_text,
        "section_context": "Opening explanation of the setting",
        "metaphor_note": "",
    }
    beat2 = {
        "beat_id": "b2",
        "scene_ids": ["scene_003", "scene_004"],
        "meaning": "Shift to another aspect of the narrative",
        "anchor_text": source[2].english_text,
        "section_context": "Follow-up context with a new emphasis",
        "metaphor_note": "A verbal transition is not a literal image.",
    }
    if genre == "history":
        middle_action, ending_action = "hold", "search"
    elif genre == "economy":
        middle_action, ending_action = "transition", "graphic"
    else:
        middle_action, ending_action = "transition", "search"
    first = slot("slot1", "b1", ["scene_001", "scene_002"],
                 source[0].english_text, goal="Introduce the physical setting")
    middle = slot("slot2", "b2", ["scene_003"], source[2].english_text,
                  action=middle_action,
                  reuse="slot1" if middle_action == "hold" else None,
                  goal="Bridge the idea, without literal footage")
    last = slot("slot3", "b2", ["scene_004"], source[3].english_text,
                action=ending_action,
                goal="Illustration of the final narrative fact")
    return {
        "format": FORMAT,
        "plan_id": "bf_s01_" + genre,
        "source_digest": script_digest(source),
        "beats": [beat1, beat2],
        "slots": [first, middle, last],
    }


@pytest.mark.parametrize("genre,search_count", [
    ("travel", 2), ("history", 2), ("economy", 1),
])
def test_three_genres_support_multi_sentence_beats_and_no_forced_search(
    genre, search_count
):
    source = scenes(genre)
    plan = parse_semantic_search_plan(example(genre), source)
    assert len(plan.beats) == 2
    assert len(plan.slots) == 3
    assert plan.slots[0].scene_ids == ("scene_001", "scene_002")
    assert len(plan.search_requests()) == search_count
    assert all(
        [q.axis for q in request.queries] == ["subject", "moment", "action"]
        for request in plan.search_requests()
    )
    assert plan.to_mapping() == example(genre)
    assert parse_semantic_search_plan(plan.to_mapping(), source) == plan


def test_abstract_transition_no_fake_lexical_provider_query():
    plan = parse_semantic_search_plan(example(), scenes())
    assert plan.slots[1].action == "transition"
    assert plan.slots[1].queries == ()
    assert [r.slot_id for r in plan.search_requests()] == ["slot1", "slot3"]
    assert "slot2" in plan.unresolved_slot_ids()


def test_hold_is_explicit_prior_visual_not_a_new_search():
    plan = parse_semantic_search_plan(example("history"), scenes("history"))
    assert plan.slots[1].reuse_from_slot_id == "slot1"
    assert plan.slots[1].action == "hold"
    assert plan.slots[1].queries == ()
    assert "slot2" not in plan.unresolved_slot_ids()


def test_graphic_does_not_request_stock_footage_as_proof():
    plan = parse_semantic_search_plan(example("economy"), scenes("economy"))
    assert plan.slots[2].action == "graphic"
    assert plan.slots[2].queries == ()
    assert set(plan.unresolved_slot_ids()) == {"slot2", "slot3"}


def test_no_match_requires_explicit_uncertainty_and_zero_queries():
    draft = example()
    draft["slots"][1]["action"] = "no_match"
    draft["slots"][1]["uncertainty"] = "No filmable evidence for this sentence"
    plan = parse_semantic_search_plan(draft, scenes())
    assert plan.slots[1].action == "no_match"
    assert "slot2" in plan.unresolved_slot_ids()


def test_one_scene_can_receive_more_than_one_separate_search_slot():
    draft = example()
    extra = slot("slot1b", "b1", ["scene_002"], scenes()[1].english_text)
    extra["queries"][0]["text"] = "fishing nets closeup"
    draft["slots"].insert(1, extra)
    plan = parse_semantic_search_plan(draft, scenes())
    assert len(plan.slots) == 4
    assert plan.slots[0].scene_ids == ("scene_001", "scene_002")
    assert plan.slots[1].scene_ids == ("scene_002",)
    assert len(plan.search_requests()) == 3


@pytest.mark.parametrize("mutate,reason", [
    (lambda p: p.update(format="not_v1"), "invalid-format"),
    (lambda p: p.update(source_digest="0" * 64), "stale-script"),
    (lambda p: p["beats"][0].update(anchor_text="Made-up words not narrated"),
     "ungrounded-beat-anchor"),
    (lambda p: p["slots"][0].update(source_text="Unrelated unsaid content"),
     "ungrounded-slot-source"),
    (lambda p: p["beats"][0].update(scene_ids=["scene_002", "scene_001"]),
     "beat-partition"),
    (lambda p: p["slots"][1].update(scene_ids=["scene_002"]),
     "invalid-slot-order-or-span"),
    (lambda p: p["slots"][0].update(beat_id="missing"), "unknown-slot-beat"),
    (lambda p: p["slots"][1].update(slot_id="slot1"), "duplicate-slot-id"),
    (lambda p: p["slots"][0].update(queries=[]), "invalid-search-slot"),
    (lambda p: p["slots"][0]["queries"][1].update(axis="subject"),
     "invalid-search-slot"),
    (lambda p: p["slots"][0]["queries"][2].update(text="coastal harbor fishing boats"),
     "invalid-search-slot"),
    (lambda p: p["slots"][0]["queries"][0].update(text="x" * 161),
     "invalid-query-text"),
    (lambda p: p["slots"][0].update(must_show=[]), "invalid-search-slot"),
    (lambda p: p["slots"][0].update(must_not_show=["visible relevant subject"]),
     "contradictory-visual-constraints"),
    (lambda p: p["slots"][1].update(queries=[{"axis": "subject", "text": "unwanted"}]),
     "invalid-nonsearch-slot"),
    (lambda p: p["slots"][0].update(evidence_type="not_applicable"),
     "invalid-search-slot"),
    (lambda p: p["slots"][0].update(entity_policy="invented"),
     "invalid-entity-policy"),
    (lambda p: p["slots"][0].update(action="imaginary"),
     "invalid-slot-action"),
    (lambda p: p["slots"][0].update(visual_brief=" " * 20),
     "invalid-visual-brief"),
    (lambda p: p["slots"].pop(), "uncovered-scenes"),
])
def test_invalid_model_suggestions_fail_closed_with_fixed_codes(mutate, reason):
    draft = example()
    mutate(draft)
    with pytest.raises(SearchPlanError, match="^" + reason + "$"):
        parse_semantic_search_plan(draft, scenes())


def test_unordered_or_duplicate_input_scene_ids_are_rejected():
    original = scenes()
    with pytest.raises(SearchPlanError, match="unordered-scenes"):
        parse_semantic_search_plan(example(), (
            replace(original[0], order=3), *original[1:]
        ))
    with pytest.raises(SearchPlanError, match="duplicate-scene-ids"):
        modified = [replace(original[1], scene_id=original[0].scene_id)]
        parse_semantic_search_plan(example(), (original[0], *modified, *original[2:]))


def test_old_plan_is_stale_if_script_changes():
    changed = list(scenes())
    changed[2] = replace(changed[2], english_text="New narration here.")
    with pytest.raises(SearchPlanError, match="stale-script"):
        parse_semantic_search_plan(example(), changed)


def test_original_scenes_and_draft_payload_remain_unchanged():
    original = scenes()
    draft = example()
    snapshot = deepcopy(draft)
    preserved = tuple(original)
    plan = parse_semantic_search_plan(draft, original)
    assert draft == snapshot
    assert original == preserved
    assert plan.to_mapping() == draft


def test_input_scripts_are_never_executed_or_disclosed_in_error_messages():
    draft = example()
    draft["slots"][0]["queries"][0]["text"] = "$([System.IO.File]::Delete('secret'))"
    plan = parse_semantic_search_plan(draft, scenes())
    assert plan.search_requests()[0].queries[0].text.startswith("$(")
    bad = deepcopy(draft)
    bad["slots"][0]["source_text"] = "PRIVATE SCRIPT NEVER REPEAT"
    with pytest.raises(SearchPlanError) as err:
        parse_semantic_search_plan(bad, scenes())
    assert "PRIVATE SCRIPT" not in str(err.value)


def test_rejects_boolean_as_scene_order_not_arbitrary_truthy_int():
    source = list(scenes())
    source[0] = replace(source[0], order=True)
    with pytest.raises(SearchPlanError, match="unordered-scenes"):
        script_digest(source)
