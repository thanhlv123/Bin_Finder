"""ZB-01 scene-first gate: synthetic examples only, no user footage or script."""
from __future__ import annotations

import json
from io import BytesIO

import pytest

from bin_finder.models import SceneContext, SceneRecord
from bin_finder.search.query_builder import build_scene_queries
from bin_finder.search.semantic_intents import (
    InvalidIntent, SceneSearchIntent, proposed_queries_for_scene,
)
from bin_finder.search.semantic_planner import LocalEditorialPlanner, SYSTEM_RULES
from bin_finder.search.reference_eval import evaluate_reference


def _plan(scene_id, narration, *, anchor, evidence, queries, uncertainty="Illustration only"):
    return {
        "scene_id": scene_id,
        "narration_text": narration,
        "scene_anchor": anchor,
        "evidence_type": evidence,
        "visual_goal": "Depict current beat honestly",
        "required_entities": [],
        "must_show": [],
        "must_not_show": [],
        "queries": queries,
        "uncertainty": uncertainty,
        "provenance": "script",
    }


def _scene(sid, narration):
    return SceneRecord(
        scene_id=sid, order=1, english_text=narration,
        context=SceneContext(keywords=()),
    )


def test_scene_02_concrete_visuals_are_kept():
    script = "Vintage automobiles pass through historic town streets."
    obj = _plan(
        "CUBA-02", script, anchor="Vintage automobiles pass",
        evidence="direct", queries=["Vintage automobiles cruising historic town streets"],
    )
    result = SceneSearchIntent.from_mapping(
        obj, scene_id="CUBA-02", narration_text=script, full_script=script
    )
    assert result.evidence_type == "direct"
    assert result.scene_anchor == "Vintage automobiles pass"


def test_scene_12_prior_context_may_resolve_a_reference_without_borrowing_topic():
    scene_text = "These vehicles undergo repeated repairs and patching to operate."
    story = "Vintage automobiles fill the streets. " + scene_text
    obj = _plan(
        "CUBA-12", scene_text, anchor="vehicles undergo repeated repairs",
        evidence="direct",
        queries=["Vintage vehicles needing repeated mechanical repairs"],
    )
    result = SceneSearchIntent.from_mapping(
        obj, scene_id="CUBA-12", narration_text=scene_text, full_script=story
    )
    assert result.queries and "vehicles" in result.queries[0].lower()


def test_scene_14_legacy_motif_context_bleed_is_rejected():
    scene_text = "Local handcrafted goods sell internationally at premium prices."
    story = "Vintage automobiles and colonial streets attract visitors. " + scene_text
    wrong = _plan(
        "CUBA-14", scene_text, anchor="handcrafted goods sell internationally",
        evidence="weak_indirect",
        queries=["Vintage automobiles parked next to colonial architecture"],
    )
    with pytest.raises(InvalidIntent, match="scene-focus"):
        SceneSearchIntent.from_mapping(
            wrong, scene_id="CUBA-14", narration_text=scene_text,
            full_script=story,
        )
    # Invalid model result must not silently become a fake relevant plan.
    assert proposed_queries_for_scene(
        _scene("CUBA-14", scene_text), wrong, full_script=story
    ) == build_scene_queries(_scene("CUBA-14", scene_text))


def test_scene_14_relevant_but_weak_illustration_is_allowed():
    scene_text = "Local handcrafted goods sell internationally at premium prices."
    good = _plan(
        "CUBA-14", scene_text, anchor="handcrafted goods sell internationally",
        evidence="weak_indirect",
        queries=["Handcrafted goods at international retail trade market"],
        uncertainty="A market shot cannot establish actual export prices.",
    )
    result = SceneSearchIntent.from_mapping(
        good, scene_id="CUBA-14", narration_text=scene_text, full_script=scene_text
    )
    assert result.evidence_type == "weak_indirect"
    assert "prices" in result.uncertainty


def test_explicit_no_match_returns_zero_queries_without_legacy_fallback():
    text = "The real value of a salary cannot be observed in a single exterior shot."
    obj = _plan(
        "CUBA-15", text, anchor="real value of a salary",
        evidence="no_match", queries=[],
        uncertainty="No exterior stock shot proves the purchasing power claim.",
    )
    intent = SceneSearchIntent.from_mapping(
        obj, scene_id="CUBA-15", narration_text=text, full_script=text,
    )
    assert intent.queries == ()
    assert proposed_queries_for_scene(
        _scene("CUBA-15", text), obj, full_script=text
    ) == []


@pytest.mark.parametrize("change", [
    {"evidence_type": "no_match", "queries": ["some misleading search"]},
    {"evidence_type": "no_match", "uncertainty": ""},
    {"evidence_type": "not_a_type"},
    {"scene_anchor": "a phrase outside the current scene"},
    {"scene_anchor": "local"},  # one weak anchor cannot ground an off-topic search
])
def test_unsafe_evidence_or_anchors_fail_closed(change):
    text = "Local handcrafted goods sell internationally at premium prices."
    obj = _plan(
        "CUBA-14", text, anchor="handcrafted goods sell internationally",
        evidence="no_match", queries=[],
        uncertainty="This price claim is not directly visually provable.",
    )
    if change.get("scene_anchor") == "local":
        obj["evidence_type"] = "contextual"
        obj["queries"] = ["vintage cars with colonial buildings"]
    obj.update(change)
    with pytest.raises(InvalidIntent):
        SceneSearchIntent.from_mapping(
            obj, scene_id="CUBA-14", narration_text=text, full_script=text,
        )


class _FakeReply:
    def __init__(self, content):
        self._buffer = BytesIO(content)

    def read(self, size):
        return self._buffer.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeOpener:
    def __init__(self, obj):
        self.obj = obj
        self.calls = []

    def open(self, req, timeout):
        self.calls.append(req)
        return _FakeReply(json.dumps({"message": {
            "content": json.dumps(self.obj)
        }}).encode("utf-8"))


def test_fake_ollama_rejects_drift_and_accepts_no_match():
    narration = "Local handcrafted goods sell internationally at premium prices."
    story = "Old cars appear earlier. " + narration
    wrong = _plan(
        "CUBA-14", narration, anchor="handcrafted goods sell internationally",
        evidence="weak_indirect", queries=["Vintage cars outside a colonial building"],
    )
    fake = _FakeOpener(wrong)
    planner = LocalEditorialPlanner(opener=fake)
    diagnostic = {}
    assert planner.propose(
        _scene("CUBA-14", narration), full_script=story, diagnostics=diagnostic
    ) is None
    assert diagnostic["reason"].startswith("invalid-intent:")
    assert len(fake.calls) == 1

    abstain = _plan(
        "CUBA-14", narration, anchor="handcrafted goods sell internationally",
        evidence="no_match", queries=[],
        uncertainty="A generic exterior scene cannot prove export prices.",
    )
    planner = LocalEditorialPlanner(opener=_FakeOpener(abstain))
    result = planner.propose(_scene("CUBA-14", narration), full_script=story)
    assert result["evidence_type"] == "no_match"
    assert result["queries"] == []


def test_reference_report_distinguishes_no_match_from_fallback():
    beats = [
        {"beat_id": f"CUBA-{i + 1:02d}",
         "start_s": 15.0 + i * 4,
         "end_s": 19.0 + i * 4,
         "script_excerpt": f"Private synthetic narration scene number {i + 1}.",
         "match_type": "weak_indirect",
         "evidence_strength": "low",
         "candidate_queries_en": ["do not send to model"],
         "must_show_english": ["do not send to model"]}
        for i in range(15)
    ]

    class NoMatchPlanner:
        def propose(self, scene, *, full_script, diagnostics):
            diagnostics["reason"] = "valid"
            return {
                "queries": [],
                "evidence_type": "no_match",
                "scene_anchor": "synthetic narration",
                "visual_goal": "No honest illustrative footage",
                "must_show": [],
                "must_not_show": [],
                "uncertainty": "No reliable imagery",
            }

    result = evaluate_reference(
        beats, start=14, count=1, approve_local_planner=True,
        planner=NoMatchPlanner(),
    )[0]
    assert result["planner_no_match"] is True
    assert result["used_legacy_fallback"] is False
    assert result["planner_queries"] == []
    assert result["model_evidence_type"] == "no_match"


def test_prompt_protects_current_scene_not_previous_motif():
    assert "CURRENT narration_text" in SYSTEM_RULES
    assert "no_match" in SYSTEM_RULES
    assert "scene_anchor" in SYSTEM_RULES
    assert "must_not_show" in SYSTEM_RULES
