"""BF-S04A.2: independent human-defined quality gate, network-free."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from bin_finder.search.editorial_local_model import parse_local_editorial_reply
from bin_finder.search.editorial_local_smoke import selected_excerpt
from bin_finder.search.editorial_quality_gate import (
    CoverageRequirement, EditorialQualityError,
    EditorialQualitySpecification, review_editorial_quality,
    savoie_editorial_reference,
)
from bin_finder.search.editorial_quality_smoke import main


def model_observed_plan():
    """Represent the user's logged BF-S04A.1R2 outcome (not an AI replay)."""
    scenes, base = selected_excerpt(2)
    shot = {
        "shot_id": "SHOT_001", "slot_id": "slot2", "beat_id": "beat2",
        "scene_ids": ["scene_002"],
        "source_anchor": scenes[0].english_text,
        "visual_brief": "Establish an alpine ski location and a gentle marked blue piste",
        "asset_evidence_type": "location_context",
        "media_type": "video", "target_duration_seconds": 3.0,
        "visual_tone": "neutral",
        "must_show": ["visible documentary subject"],
        "must_not_show": ["fake original accident footage", "unlabeled reenactment"],
        "search_queries": [{
            "language": "en",
            "text": "blue ski piste marker in alpine ski resort",
        }],
        "fallback_policy": "no_match",
    }
    plan = parse_local_editorial_reply(json.dumps({"shots": [shot]}), base, scenes)
    return plan, scenes, base, shot


def test_observed_ai_result_has_two_covered_and_three_missing_requirements():
    plan, _, _, _ = model_observed_plan()
    r = review_editorial_quality(plan, savoie_editorial_reference())
    assert r.status == "quality-review-required"
    assert r.shot_count == 1
    assert r.covered == ("ski_location", "gentle_blue_piste")
    assert r.missing == (
        "savoie_context", "skier_descending", "safe_afterfall_transition"
    )
    assert r.flags == (
        "editorial-coverage-incomplete",
        "generic-visible-criteria",
        "missing-somber-or-suspense-transition",
        "single-shot-editorial-compression-review",
    )
    assert r.as_mapping()["human_editorial_review_required"] is True
    assert r.as_mapping()["footage_verified"] is False
    assert r.as_mapping()["rights_approved"] is False
    assert r.as_mapping()["timeline_approved"] is False


def test_source_anchor_must_not_count_as_actual_visual_coverage():
    plan, scenes, base, shot = model_observed_plan()
    # Original source narration contains Savoie and an injured/unconscious
    # person, but neither is requested by the actual AI shot.
    assert "Savoie" in plan.shots[0].source_anchor
    assert "Inconscient." in plan.shots[0].source_anchor
    r = review_editorial_quality(plan, savoie_editorial_reference())
    assert "savoie_context" in r.missing
    assert "safe_afterfall_transition" in r.missing


def test_must_not_show_exclusion_must_not_count_as_positive_coverage():
    plan, scenes, base, shot = model_observed_plan()
    r = review_editorial_quality(plan, savoie_editorial_reference())
    assert "safe_afterfall_transition" in r.missing
    assert "fake original accident footage" in plan.shots[0].must_not_show


def test_editor_authored_three_shots_cover_more_concepts_but_not_safe_aftermath():
    from bin_finder.search.editorial_shot_smoke import (
        source_and_base, proposed_shots,
    )
    _, full = source_and_base()
    scenes, mini = selected_excerpt(2)
    payload = proposed_shots(full)
    rows = [x for x in payload["shots"] if x["slot_id"] == "slot2"]
    plan = parse_local_editorial_reply(
        json.dumps({"shots": rows}, ensure_ascii=False), mini, scenes
    )
    r = review_editorial_quality(plan, savoie_editorial_reference())
    assert r.shot_count == 3
    assert r.covered == (
        "ski_location", "savoie_context", "gentle_blue_piste",
        "skier_descending",
    )
    assert r.missing == ("safe_afterfall_transition",)
    assert "missing-somber-or-suspense-transition" not in r.flags


def test_added_somber_text_transition_covers_all_reference_requirements():
    from bin_finder.search.editorial_shot_smoke import (
        source_and_base, proposed_shots,
    )
    _, full = source_and_base()
    scenes, mini = selected_excerpt(2)
    rows = [deepcopy(x) for x in proposed_shots(full)["shots"]
            if x["slot_id"] == "slot2"]
    rows.append({
        "shot_id": "SHOT_AFTERFALL", "slot_id": "slot2", "beat_id": "beat2",
        "scene_ids": ["scene_002"], "source_anchor": "Inconscient.",
        "visual_brief": "Cut to black with a title about the aftermath",
        "asset_evidence_type": "graphic", "media_type": "graphic",
        "target_duration_seconds": 1.5, "visual_tone": "somber",
        "must_show": [], "must_not_show": [], "search_queries": [],
        "fallback_policy": "graphic_with_source",
    })
    plan = parse_local_editorial_reply(
        json.dumps({"shots": rows}, ensure_ascii=False), mini, scenes
    )
    r = review_editorial_quality(plan, savoie_editorial_reference())
    assert len(r.covered) == 5
    assert r.missing == ()
    assert "editorial-coverage-incomplete" not in r.flags
    assert r.status == "quality-review-required"  # even 5/5 != source proof


def test_synthetic_textual_coverage_avoids_partial_word_false_positive():
    plan, scenes, base, shot = model_observed_plan()
    spec = EditorialQualitySpecification(
        "slot2", (CoverageRequirement("random", "Test bounded phrase",
                                    ("resortment",)),)
    )
    r = review_editorial_quality(plan, spec)
    assert r.covered == ()
    assert r.missing == ("random",)


def test_generic_must_show_is_flagged_separately_from_content_coverage():
    plan, _, _, _ = model_observed_plan()
    spec = EditorialQualitySpecification(
        "slot2", (CoverageRequirement("snow", "Alpine context",
                                    ("alpine ski",)),)
    )
    r = review_editorial_quality(plan, spec)
    assert r.missing == ()
    assert "generic-visible-criteria" in r.flags
    assert "single-shot-editorial-compression-review" not in r.flags


@pytest.mark.parametrize("code", ["", "BAD", "x space", "x<script>", "ü", "9first"])
def test_reject_bad_requirement_identifier(code):
    with pytest.raises(EditorialQualityError, match="invalid-coverage-code"):
        CoverageRequirement(code, "Test coverage", ("blue ski piste",))


@pytest.mark.parametrize("phrases", [(), ("",), (" ",), ("x" * 121,)])
def test_reject_empty_or_unbounded_requirement_phrases(phrases):
    with pytest.raises(EditorialQualityError, match="invalid-coverage-phrase|invalid-coverage-requirement"):
        CoverageRequirement("requirement", "Test coverage", phrases)


def test_duplicate_quality_codes_rejected():
    requirement = CoverageRequirement("duplicate", "Something", ("skier",))
    with pytest.raises(EditorialQualityError, match="invalid-quality-requirements"):
        EditorialQualitySpecification("slot2", (requirement, requirement))


def test_wrong_slot_does_not_guess_or_search():
    plan, _, _, _ = model_observed_plan()
    spec = EditorialQualitySpecification(
        "slot3", (CoverageRequirement("context", "Test", ("snow",)),)
    )
    with pytest.raises(EditorialQualityError, match="quality-slot-not-planned"):
        review_editorial_quality(plan, spec)


def test_quality_review_does_not_modify_ai_output_or_require_network():
    plan, _, _, _ = model_observed_plan()
    before = plan.to_mapping()
    r = review_editorial_quality(plan, savoie_editorial_reference())
    assert plan.to_mapping() == before
    assert r.as_mapping()["human_editorial_review_required"] is True


def test_cli_readonly_user_style_json(tmp_path, capsys):
    plan, _, _, _ = model_observed_plan()
    path = tmp_path / "savoie.json"
    path.write_text(json.dumps(plan.to_mapping(), ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    assert main(["--plan-json", str(path)]) == 0
    out = capsys.readouterr().out
    assert "BFS04A2_OLLAMA_CALLS: 0" in out
    assert "BFS04A2_PROVIDER_CALLS: 0" in out
    assert "BFS04A2_COVERED: ski_location,gentle_blue_piste" in out
    assert "BFS04A2_MISSING: savoie_context,skier_descending,safe_afterfall_transition" in out
    assert "BFS04A2_HUMAN_EDITORIAL_REVIEW: True" in out
    assert path.read_bytes() == before


def test_cli_reject_invalid_plan_json_or_wrong_suffix_without_printing_data(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text('{"format":"forged","secret":"DO_NOT_PRINT"}', encoding="utf-8")
    assert main(["--plan-json", str(path)]) == 2
    o = capsys.readouterr().out
    assert "invalid-or-mismatched-plan" in o
    assert "DO_NOT_PRINT" not in o
    assert main(["--plan-json", str(tmp_path / "missing.txt")]) == 2
    o = capsys.readouterr().out
    assert "invalid-local-file" in o


def test_cli_reject_oversize_file_without_reading(tmp_path, capsys):
    path = tmp_path / "large.json"
    path.write_bytes(b"x" * 262145)
    assert main(["--plan-json", str(path)]) == 2
    assert "oversized-local-plan" in capsys.readouterr().out
