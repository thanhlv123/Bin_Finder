"""ZB-VIDEO-01 regression tests with synthetic references; no copyrighted frames."""
from __future__ import annotations

import json

import pytest

from bin_finder.search import reference_eval as target


def _reference():
    beats = []
    for i in range(15):
        start = 15.0 + i * 4.0
        beats.append({
            "beat_id": f"CUBA-{i + 1:02d}",
            "start_s": start,
            "end_s": start + 4.0,
            "script_excerpt": f"An old Cuban mechanic repairs a vintage car near Havana {i + 1}.",
            "match_type": "direct" if i < 11 else "editorial_metaphor",
            "evidence_strength": "high" if i < 11 else "low",
            "must_show_english": ["car repair"],
            "candidate_queries_en": ["PRIVATE_REFERENCE_QUERY"], 
        })
    return {"format": "bin_finder_cuba_reference_v1", "beats": beats}


def test_private_reference_load_and_offline_only(tmp_path, monkeypatch):
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(_reference()), encoding="utf-8")
    class ForbiddenPlanner:
        def __init__(self, *args, **kwargs):
            raise AssertionError("No network/model initialization without consent")
    monkeypatch.setattr(target, "LocalEditorialPlanner", ForbiddenPlanner)
    beats = target.load_reference(path)
    assert len(beats) == 15
    result = target.evaluate_reference(beats, start=1, count=3)
    assert len(result) == 3
    assert result[0]["planner_status"] == "NOT_RUN_NO_APPROVAL"
    assert result[0]["reference_is_preliminary"] is True
    assert result[0]["beat_id"] == "CUBA-01"
    assert all("planner_queries" not in r for r in result)


def test_cli_without_approval_does_not_contact_model(tmp_path, monkeypatch, capsys):
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(_reference()), encoding="utf-8")
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected model")
    monkeypatch.setattr(target, "LocalEditorialPlanner", forbidden)
    assert target.main(["--reference", str(path)]) == 0
    output = capsys.readouterr().out
    assert output.count("ZB_VIDEO_RESULT:") == 1
    assert "NOT_RUN_NO_APPROVAL" in output
    assert "no provider search" in output


def test_approved_fake_planner_receives_only_narration():
    beats = _reference()["beats"]
    class FakePlanner:
        def __init__(self):
            self.calls = []
        def propose(self, scene, *, full_script, diagnostics):
            self.calls.append((scene.scene_id, full_script))
            diagnostics["reason"] = "valid"
            return {
                "queries": ["Havana mechanic repairing vintage car"],
                "visual_goal": "Show mechanic working",
                "must_show": ["car repair"],
                "must_not_show": ["unrelated concert"],
                "uncertainty": "Still a visual illustration",
            }
    planner = FakePlanner()
    result = target.evaluate_reference(
        beats, start=12, count=2, approve_local_planner=True, planner=planner
    )
    assert [x["beat_id"] for x in result] == ["CUBA-12", "CUBA-13"]
    assert all(x["planner_status"] == "valid" for x in result)
    assert all(not x["used_legacy_fallback"] for x in result)
    assert len(planner.calls) == 2
    assert all("PRIVATE_REFERENCE_QUERY" not in full for _, full in planner.calls)
    assert all("car repair" not in full for _, full in planner.calls)


def test_approved_fake_planner_fallback():
    beats = _reference()["beats"]
    class FakeFallback:
        def propose(self, scene, *, full_script, diagnostics):
            diagnostics["reason"] = "invalid-intent:missing-queries"
            return None
    result = target.evaluate_reference(
        beats, count=1, approve_local_planner=True, planner=FakeFallback()
    )[0]
    assert result["used_legacy_fallback"] is True
    assert result["planner_queries"] == result["legacy_queries"]


@pytest.mark.parametrize("bad", [
    lambda d: d.update(format="other"),
    lambda d: d["beats"].pop(),
    lambda d: d["beats"][1].update(beat_id="CUBA-01"),
    lambda d: d["beats"][2].update(start_s=35),
    lambda d: d["beats"][0].update(candidate_queries_en=[]),
    lambda d: d["beats"][0].update(match_type="unknown"),
])
def test_reject_corrupt_reference(tmp_path, bad):
    document = _reference()
    bad(document)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(target.ReferenceError):
        target.load_reference(path)


def test_invalid_ranges_never_call_planner():
    beats = _reference()["beats"]
    with pytest.raises(target.ReferenceError):
        target.evaluate_reference(beats, start=15, count=2, approve_local_planner=True)
    with pytest.raises(target.ReferenceError):
        target.evaluate_reference(beats, start=0)
    with pytest.raises(target.ReferenceError):
        target.evaluate_reference(beats, count=16)


def test_reject_unapproved_injected_planner():
    with pytest.raises(target.ReferenceError):
        target.evaluate_reference(_reference()["beats"], planner=object())


def test_rejected_inspection_requires_explicit_model_approval(tmp_path, capsys):
    path = tmp_path / "reference.json"
    path.write_text(json.dumps(_reference()), encoding="utf-8")
    assert target.main(["--reference", str(path), "--inspect-rejected"]) == 2
    assert "inspection-requires-local-planner-approval" in capsys.readouterr().out


def test_opt_in_rejection_preview_passes_only_selected_bounded_fields():
    class RejectedPlanner:
        def propose(self, scene, *, full_script, diagnostics, inspect_rejection):
            assert inspect_rejection is True
            assert "PRIVATE_REFERENCE_QUERY" not in full_script
            diagnostics["reason"] = "invalid-intent:insufficient-scene-focus"
            diagnostics["rejected_plan_preview"] = {
                "scene_anchor": "machines repaired",
                "queries": ["old classic car repair"],
                "evidence_type": "direct",
            }
            return None

    result = target.evaluate_reference(
        _reference()["beats"], start=12, count=1,
        approve_local_planner=True,
        inspect_rejection=True, planner=RejectedPlanner(),
    )[0]
    assert result["used_legacy_fallback"] is True
    assert result["planner_diagnostics"]["rejected_plan_preview"]["queries"] == [
        "old classic car repair"
    ]
    assert result["planner_status"] == "invalid-intent:insufficient-scene-focus"
