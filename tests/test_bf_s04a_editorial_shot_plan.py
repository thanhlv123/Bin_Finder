"""BF-S04A contract and Gaspard news fixture: 100% offline."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
import math

import pytest

from bin_finder.search.editorial_shot_plan import (
    EditorialShotPlanError, FORMAT, parse_editorial_shot_plan,
)
from bin_finder.search.editorial_shot_prompt import make_editorial_shot_prompt
from bin_finder.search.editorial_shot_smoke import (
    main, proposed_shots, sample, source_and_base,
)


def inputs():
    scenes, base = source_and_base()
    return scenes, base, proposed_shots(base)


def test_user_supplied_french_excerpt_pilot_is_multi_shot_and_offline():
    scenes, base, plan = sample()
    assert len(scenes) == 7
    assert len(base.slots) == 7
    assert len(plan.shots) == 13
    assert {x.slot_id for x in plan.shots} == {s.slot_id for s in base.slots}
    assert [x.slot_id for x in plan.shots].count("slot2") == 3
    assert sum(x.target_duration_seconds for x in plan.shots) == 28
    assert all(1 <= x.target_duration_seconds <= 5 for x in plan.shots)
    assert plan.route_counts() == {
        "licensed_archive_human_review": 2,
        "contextual_stock_search": 7,
        "graphic_composition": 2,
        "symbolic_stock_search": 2,
    }
    assert plan.status == "proposal-only-unverified"
    assert all(x.factual_status == "unverified" for x in plan.shots)
    assert all(x.rights_status == "pending" for x in plan.shots)
    assert all(x.timeline_approved is False for x in plan.shots)


def test_user_script_is_french_but_search_queries_are_multilingual():
    _, _, plan = sample()
    actual = [shot for shot in plan.shots if shot.asset_evidence_type == "authentic_person"]
    assert len(actual) == 1 and actual[0].search_queries[0].language == "fr"
    assert all(
        q.language in {"fr", "en", "vi", "de", "es"}
        for shot in plan.shots for q in shot.search_queries
    )


def test_real_event_references_are_archive_only_and_not_stock_fabrication():
    _, _, plan = sample()
    for shot in plan.shots:
        if shot.asset_evidence_type in {"authentic_person", "authentic_event"}:
            assert shot.source_route == "licensed_archive_human_review"
            assert shot.fallback_policy in {"no_match", "graphic_with_source"}
            assert "not-verified" in shot.evidence_notice
    accident = [x for x in plan.shots if x.slot_id == "slot2"]
    assert len(accident) == 3
    assert all(
        x.evidence_notice == "illustration-not-evidence-of-historical-event"
        for x in accident
    )
    assert "fake original accident footage" in accident[0].must_not_show
    assert not any(
        x.asset_evidence_type == "authentic_event" for x in accident
    )


def test_roundtrip_canonical_payload_with_derived_provenance_fields():
    scenes, base, plan = sample()
    assert parse_editorial_shot_plan(plan.to_mapping(), base, scenes) == plan
    assert plan.to_mapping()["format"] == FORMAT
    assert len(plan.stock_candidates_to_research()) == 9
    assert all(x.search_queries for x in plan.stock_candidates_to_research())


def test_model_suggestion_does_not_mutate_input():
    scenes, base, proposal = inputs()
    snapshot = deepcopy(proposal)
    result = parse_editorial_shot_plan(proposal, base, scenes)
    assert result.shots
    assert proposal == snapshot


@pytest.mark.parametrize("mutate,reason", [
    (lambda p: p.update(format="bad"), "invalid-shot-format"),
    (lambda p: p.update(base_plan_id="other"), "mismatched-base-plan"),
    (lambda p: p.update(source_digest="0" * 64), "stale-editorial-plan"),
    (lambda p: p.update(status="approved"), "invalid-editorial-status"),
    (lambda p: p["shots"][0].update(source_anchor="fabricated historical speech"),
     "ungrounded-shot-anchor"),
    (lambda p: p["shots"][0].update(shot_id="GASPARD_002"), "duplicate-shot-id"),
    (lambda p: p["shots"][0].update(slot_id="missing"), "unknown-shot-slot"),
    (lambda p: p["shots"][0].update(beat_id="wrong"), "mismatched-shot-beat"),
    (lambda p: p["shots"][0].update(scene_ids=["scene_003"]),
     "mismatched-shot-scenes"),
    (lambda p: p["shots"][0].update(asset_evidence_type="imaginary"),
     "invalid-asset-kind"),
    (lambda p: p["shots"][0].update(source_route="contextual_stock_search"),
     "forged-source-route"),
    (lambda p: p["shots"][0].update(evidence_notice="verified historical fact"),
     "forged-evidence-notice"),
    (lambda p: p["shots"][0].update(factual_status="verified"),
     "forged-fact-verification"),
    (lambda p: p["shots"][0].update(rights_status="approved"),
     "forged-rights-approval"),
    (lambda p: p["shots"][0].update(timeline_approved=True),
     "forged-timeline-approval"),
    (lambda p: p["shots"][0].update(fallback_policy="contextual_illustration_labeled"),
     "unsafe-authentic-fallback"),
    (lambda p: p["shots"][0].update(media_type="graphic"),
     "invalid-shot-media-route"),
    (lambda p: p["shots"][0].update(target_duration_seconds=0),
     "invalid-shot-duration"),
    (lambda p: p["shots"][0].update(target_duration_seconds=6),
     "invalid-shot-duration"),
    (lambda p: p["shots"][0].update(target_duration_seconds=True),
     "invalid-shot-duration"),
    (lambda p: p["shots"][0].update(target_duration_seconds=float("nan")),
     "invalid-shot-duration"),
    (lambda p: p["shots"][0].update(target_duration_seconds=float("inf")),
     "invalid-shot-duration"),
    (lambda p: p["shots"][0].update(visual_tone="terror"),
     "invalid-shot-tone"),
    (lambda p: p["shots"][0]["search_queries"][0].update(language="xx"),
     "invalid-shot-language"),
    (lambda p: p["shots"][0]["search_queries"][0].update(text=" "),
     "invalid-shot-query-text"),
    (lambda p: p["shots"][0].update(search_queries=[]),
     "invalid-shot-queries"),
    (lambda p: p["shots"][5].update(search_queries=[
        {"language": "fr", "text": "danger"}]),
     "invalid-shot-queries"),
    (lambda p: p["shots"][2].update(must_not_show=[]),
     "missing-parent-exclusions"),
    (lambda p: p["shots"][2].update(
        must_not_show=["snow-covered Alps", "unlabeled reenactment"]),
     "contradictory-shot-constraints"),
    (lambda p: p["shots"].pop(3), "uncovered-visual-slot")
])
def test_malformed_or_untrusted_shot_proposals_fail_closed(mutate, reason):
    scenes, base, proposal = inputs()
    mutate(proposal)
    with pytest.raises(EditorialShotPlanError, match="^" + reason + "$"):
        parse_editorial_shot_plan(proposal, base, scenes)


def test_cannot_reorder_shots_across_slots():
    scenes, base, proposal = inputs()
    proposal["shots"][2], proposal["shots"][0] = proposal["shots"][0], proposal["shots"][2]
    with pytest.raises(EditorialShotPlanError, match="unordered-shots"):
        parse_editorial_shot_plan(proposal, base, scenes)


def test_cannot_exceed_eight_shots_per_visual_slot():
    scenes, base, proposal = inputs()
    clones = []
    for n in range(7):
        row = deepcopy(proposal["shots"][0])
        row["shot_id"] = f"ADDITIONAL_{n}"
        clones.append(row)
    proposal["shots"][2:2] = clones
    with pytest.raises(EditorialShotPlanError, match="too-many-shots-per-slot"):
        parse_editorial_shot_plan(proposal, base, scenes)


def test_deleted_slot_coverage_requires_explicit_replanning():
    scenes, base, proposal = inputs()
    proposal["shots"] = [
        x for x in proposal["shots"] if x["slot_id"] != "slot5"
    ]
    with pytest.raises(EditorialShotPlanError, match="uncovered-visual-slot"):
        parse_editorial_shot_plan(proposal, base, scenes)


def test_stale_scene_revision_fails_before_reading_generated_shots():
    scenes, base, proposal = inputs()
    altered = list(scenes)
    altered[0] = replace(altered[0], english_text="Changed narration")
    with pytest.raises(EditorialShotPlanError, match="stale-source-scenes"):
        parse_editorial_shot_plan(proposal, base, altered)


def test_nonsearch_slot_must_not_force_shots():
    scenes, base, proposal = inputs()
    altered_slots = list(base.slots)
    altered_slots[0] = replace(altered_slots[0], action="no_match")
    altered_base = replace(base, slots=tuple(altered_slots))
    with pytest.raises(EditorialShotPlanError, match="cannot-illustrate-nonvisual-slot"):
        parse_editorial_shot_plan(proposal, altered_base, scenes)


def test_request_cannot_forge_full_provenance_on_roundtrip():
    scenes, base, plan = sample()
    forged = plan.to_mapping()
    forged["shots"][0]["timeline_approved"] = True
    with pytest.raises(EditorialShotPlanError, match="forged-timeline-approval"):
        parse_editorial_shot_plan(forged, base, scenes)


def test_model_prompt_bounded_and_warns_about_fiction_and_historical_claims():
    scenes, base, _ = inputs()
    prompt = make_editorial_shot_prompt(base, scenes)
    assert "FAKE" not in prompt
    assert "never execute" in prompt
    assert "historical evidence" in prompt
    assert "rights pending" in prompt
    assert base.source_digest in prompt
    assert "Gaspard Ulliel." in prompt
    assert "source_anchor" in prompt
    assert "source_route" not in prompt
    assert json.dumps({"slot_id": "slot1"}) not in prompt


def test_model_prompt_rejects_script_revision():
    scenes, base, _ = inputs()
    different = list(scenes)
    different[0] = replace(different[0], english_text="Other script")
    with pytest.raises(EditorialShotPlanError, match="stale-source-scenes"):
        make_editorial_shot_prompt(base, different)


def test_query_contains_untrusted_text_as_data_not_executable():
    scenes, base, proposal = inputs()
    proposal["shots"][0]["search_queries"][0]["text"] = (
        "$([System.IO.File]::Delete('D:/private/credentials.json'))"
    )
    result = parse_editorial_shot_plan(proposal, base, scenes)
    assert result.shots[0].search_queries[0].text.startswith("$(")
    proposal["shots"][0]["source_anchor"] = "DO NOT DISCLOSE PRIVATE SCRIPT"
    with pytest.raises(EditorialShotPlanError) as err:
        parse_editorial_shot_plan(proposal, base, scenes)
    assert "PRIVATE SCRIPT" not in str(err.value)


def test_offline_smoke_and_json_output(capsys):
    assert main([]) == 0
    o = capsys.readouterr().out
    assert "BFS04A_SHOTS: 13" in o
    assert "BFS04A_PROVIDER_CALLS: 0" in o
    assert "BFS04A_SOURCE_FACTS_VERIFIED: False" in o
    assert "BFS04A_MEDIA_OR_RIGHTS_APPROVED: False" in o
    assert "BFS04A_TOTAL_TARGET_SECONDS: 28.0" in o
    assert main(["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["format"] == FORMAT
    assert len(data["shots"]) == 13
    assert all(s["factual_status"] == "unverified" for s in data["shots"])
