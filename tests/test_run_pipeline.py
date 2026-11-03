"""Offline orchestration acceptance and invalidation tests."""
from dataclasses import replace
from pathlib import Path
import json

from bin_finder.run import RunOptions, RunServices, run_pipeline
from bin_finder.run.cli import main
from bin_finder.run.steps import read_json
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.matching.models import SelectionPlan
from bin_finder.production.media import MediaInfo
from bin_finder.qa.models import QaReport, Finding
from test_footage_service import FakeProvider
from test_production_tts import FakeEngine


def services_for(tmp_path):
    """Use real package logic around fully offline boundaries."""
    def scorer(footage, briefs, config, **kwargs):
        cues = []
        for cue in footage.cues:
            candidate = cue["candidates"][0]
            ranked = {**candidate, "final_score": 1, "text_score": 1, "vlm": None, "reasons": []}
            cues.append({"cue_id": cue["cue_id"], "text": cue["text"], "ranked": [ranked],
                         "selected_source_id": candidate["source_id"], "suggested_source_id": candidate["source_id"],
                         "status": "auto_selected", "flags": [], "confidence": 1, "selection_origin": "auto"})
        return SelectionPlan("selection_plan_v1", "hash", footage.brief_sha256, footage.script_sha256, {}, cues, {})

    def renderer(timeline, narration, output, work_dir, config):
        output.write_bytes(b"offline-video")

    def exporter(source, output, target, **kwargs):
        output.write_bytes(source.read_bytes())
        return {}

    return RunServices(footage_registry_factory=lambda root: ProviderRegistry([FakeProvider("pexels")]),
                       matching_scorer=scorer, speech_engine_factory=FakeEngine,
                       media_loader=lambda *args: tmp_path / "source.mp4",
                       media_probe=lambda *args: MediaInfo(100, 1920, 1080), renderer=renderer,
                       qa_evaluator=lambda *args: QaReport(str(args[0]), str(args[1]), "now"), exporter=exporter)


def setup_run(tmp_path):
    script = tmp_path / "script.txt"
    script.write_text("Red sunrise.", encoding="utf-8")
    options = RunOptions(project_root=tmp_path, brief_provider="heuristic", sources=["pexels"], no_vlm=True)
    return script, tmp_path / "out", options, services_for(tmp_path)


def test_complete_and_resume(tmp_path):
    script, output, options, services = setup_run(tmp_path)
    assert run_pipeline(script, output, options, services=services) == 0
    state = read_json(output / "run-state.json")
    assert state["status"] == "completed"
    assert all(step["status"] == "done" for step in state["steps"])
    assert state["steps"][0]["summary"]["cues"] == 1
    assert state["steps"][4]["summary"]["passed"]
    for step in state["steps"]:
        assert step["inputs"]
        assert all(Path(path).is_file() for path in step["outputs"])
    assert "Complete:" in (output / "run.log").read_text(encoding="utf-8")
    assert (output / "final.mp4").exists()
    def forbidden(*args):
        raise AssertionError("Resume called a factory")
    resumed = replace(options, resume=True)
    assert run_pipeline(script, output, resumed, services=RunServices(brief_provider_factory=forbidden)) == 0
    assert all(step["status"] == "skipped" for step in read_json(output / "run-state.json")["steps"])
    assert run_pipeline(script, output, resumed, services=RunServices(brief_provider_factory=forbidden)) == 0
    script.write_text("Blue sky.", encoding="utf-8")
    assert run_pipeline(script, output, resumed, services=services) == 0
    assert read_json(output / "run-state.json")["steps"][0]["status"] == "done"


def test_failure_resume(tmp_path):
    script, output, options, services = setup_run(tmp_path)
    def fail(root):
        raise RuntimeError("private diagnostic")
    assert run_pipeline(script, output, options, services=replace(services, footage_registry_factory=fail)) == 1
    state = read_json(output / "run-state.json")
    assert state["steps"][1]["error"]["type"] == "RuntimeError"
    assert state["steps"][2]["status"] == "pending"
    assert run_pipeline(script, output, replace(options, resume=True), services=services) == 0
    assert read_json(output / "run-state.json")["steps"][0]["status"] == "skipped"


def test_needs_review_and_allow(tmp_path, capsys):
    script, output, options, services = setup_run(tmp_path)
    original = services.matching_scorer
    def unselected(*args, **kwargs):
        plan = original(*args, **kwargs)
        for cue in plan.cues:
            cue.update(selected_source_id=None, status="needs_review")
        return plan
    services = replace(services, matching_scorer=unselected)
    assert run_pipeline(script, output, options, services=services) == 4
    assert "review.html" in capsys.readouterr().out
    assert read_json(output / "run-state.json")["status"] == "needs_review"
    assert run_pipeline(script, output, replace(options, resume=True, allow_suggested=True), services=services) == 0


def test_qa_blocker(tmp_path):
    script, output, options, services = setup_run(tmp_path)
    evaluator = lambda *args: QaReport("video", "production", "now", [Finding("test", "blocker", "blocked")])
    services = replace(services, qa_evaluator=evaluator)
    assert run_pipeline(script, output, replace(options, strict_qa=True), services=services) == 3
    assert not (output / "final.mp4").exists()
    assert read_json(output / "run-state.json")["status"] == "blocked"


def test_decisions_invalidation(tmp_path):
    script, output, options, services = setup_run(tmp_path)
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps({"version": 1, "decisions": {}}))
    options = replace(options, decisions=decisions)
    assert run_pipeline(script, output, options, services=services) == 0
    decisions.write_text(json.dumps({"version": 1, "decisions": {}}, indent=2))
    assert run_pipeline(script, output, replace(options, resume=True), services=services) == 0
    steps = read_json(output / "run-state.json")["steps"]
    assert [step["status"] for step in steps[:3]] == ["skipped", "skipped", "done"]


def test_batch_continues(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("a", "b", "c"):
        (scripts / (name + ".txt")).write_text("Red sunrise.")
    services = services_for(tmp_path)
    original = services.matching_scorer
    calls = []
    def scorer(*args, **kwargs):
        calls.append(True)
        if len(calls) == 2:
            raise RuntimeError("offline failure")
        return original(*args, **kwargs)
    config = tmp_path / "run.json"
    config.write_text(json.dumps({"brief": {"provider": "heuristic"}, "footage": {"sources": ["pexels"]}}))
    output = tmp_path / "batch"
    assert main(["--batch", str(scripts), "-o", str(output), "--config", str(config), "--project-root", str(tmp_path)],
                services=replace(services, matching_scorer=scorer)) == 1
    results = read_json(output / "batch-summary.json")["scripts"]
    assert [result["exit_code"] for result in results] == [0, 1, 0]


def test_decisions_resolve_review(tmp_path):
    script, output, options, services = setup_run(tmp_path)
    original = services.matching_scorer
    def unselected(*args, **kwargs):
        plan = original(*args, **kwargs)
        plan.cues[0].update(selected_source_id=None, status="needs_review")
        return plan
    services = replace(services, matching_scorer=unselected)
    assert run_pipeline(script, output, options, services=services) == 4
    selection = read_json(output / "selection.json")["cues"][0]
    decisions = tmp_path / "decisions.json"
    decisions.write_text(json.dumps({"version": 1, "decisions": {
        selection["cue_id"]: {"source_id": selection["suggested_source_id"], "lock": True}}}))
    assert run_pipeline(script, output, replace(options, decisions=decisions, resume=True), services=services) == 0


def test_partial_and_from_step_validation(tmp_path):
    script, output, options, services = setup_run(tmp_path)
    assert run_pipeline(script, output, replace(options, until_step="brief"), services=services) == 0
    assert not (output / "footage.json").exists()
    resumed = replace(options, from_step="footage", resume=True)
    assert run_pipeline(script, output, resumed, services=services) == 0
    script.write_text("Changed script.")
    assert run_pipeline(script, output, resumed, services=services) == 2


def test_blocked_rerun_removes_stale_export(tmp_path):
    script, output, options, services = setup_run(tmp_path)
    assert run_pipeline(script, output, options, services=services) == 0
    evaluator = lambda *args: QaReport("video", "production", "now", [Finding("test", "blocker", "blocked")])
    assert run_pipeline(script, output, options, services=replace(services, qa_evaluator=evaluator)) == 3
    assert not (output / "final.mp4").exists()
    state = read_json(output / "run-state.json")
    assert state["steps"][5]["status"] == "blocked"


def test_real_matching_without_vlm(tmp_path):
    script, output, options, services = setup_run(tmp_path)
    services = replace(services, matching_scorer=None)
    assert run_pipeline(script, output, replace(options, allow_suggested=True), services=services) == 0
    assert read_json(output / "selection.json")["stats"]["vlm_calls"] == 0


def test_limit_cues_before_provider(tmp_path):
    from bin_finder.brief import BriefConfig, plan_briefs
    from bin_finder.brief.providers import HeuristicBriefProvider

    script, output, options, services = setup_run(tmp_path)
    narration = "# First\nA red sun rises. The birds fly away.\n# Second\nThe clouds move slowly."
    script.write_text(narration, encoding="utf-8")
    config = BriefConfig(provider="heuristic")
    complete = plan_briefs(narration, config)
    received = []

    class CountingProvider(HeuristicBriefProvider):
        def propose(self, cues, context):
            received.extend(cues)
            assert context["cues"] == cues
            return super().propose(cues, context)

    services = replace(services, brief_provider_factory=CountingProvider)
    assert run_pipeline(script, output, replace(options, limit_cues=2, until_step="brief"), services=services) == 0
    assert received == complete.cues[:2]
    assert read_json(output / "brief.json")["cues"] == [cue.to_dict() for cue in complete.cues[:2]]


def test_resume_review_reuses_matching(tmp_path):
    script, output, options, services = setup_run(tmp_path)
    original = services.matching_scorer
    calls = []

    def scorer(*args, **kwargs):
        calls.append(True)
        plan = original(*args, **kwargs)
        plan.cues[0].update(selected_source_id=None, status="needs_review")
        return plan

    services = replace(services, matching_scorer=scorer)
    assert run_pipeline(script, output, options, services=services) == 4
    matching = read_json(output / "run-state.json")["steps"][2]
    assert matching["status"] == "needs_review"
    assert matching["inputs"] and matching["outputs"] and matching["output_hashes"]
    assert run_pipeline(script, output, replace(options, resume=True), services=services) == 4
    assert len(calls) == 1
    assert run_pipeline(script, output, replace(options, resume=True, allow_suggested=True), services=services) == 0
    steps = read_json(output / "run-state.json")["steps"]
    assert steps[2]["status"] == "skipped"
    assert steps[3]["status"] == "done"
    assert len(calls) == 1


def test_step_error_redaction_and_traceback(tmp_path, capsys):
    from bin_finder.run.logging import step_error
    from urllib.error import URLError

    for error in (ConnectionError("offline"), URLError("offline"), RuntimeError("connection refused 3900")):
        assert "hãy mở VoiceStudio" in step_error("production", error)
    assert "VoiceStudio" not in step_error("production", RuntimeError("render failed"))
    script, output, options, services = setup_run(tmp_path)
    secrets = ["sk-abc123", "bearer-secret", "key-secret", "token-secret", "api-secret", "A1" * 20]

    def fail(root):
        raise RuntimeError("render failed\n sk-abc123 Bearer bearer-secret key=key-secret token=token-secret api_key: api-secret " + secrets[-1] + " x" * 300)

    services = replace(services, footage_registry_factory=fail)
    assert run_pipeline(script, output, options, services=services) == 1
    console = capsys.readouterr().out
    logfile = (output / "run.log").read_text(encoding="utf-8")
    state_text = (output / "run-state.json").read_text(encoding="utf-8")
    message = read_json(output / "run-state.json")["steps"][1]["error"]["message"]
    assert "render failed" in message
    assert len(message) <= 300 and "\n" not in message
    assert "Traceback (most recent call last)" in logfile
    assert "Traceback (most recent call last)" not in console
    for secret in secrets:
        assert secret not in console + logfile + state_text


def test_modified_matching_output_invalidates_resume(tmp_path):
    script, output, options, services = setup_run(tmp_path)
    assert run_pipeline(script, output, options, services=services) == 0
    review = output / "review.html"
    review.write_text("changed", encoding="utf-8")
    assert run_pipeline(script, output, replace(options, resume=True), services=services) == 0
    assert read_json(output / "run-state.json")["steps"][2]["status"] == "done"


def test_production_connection_hint_is_specific(tmp_path, capsys):
    script, output, options, services = setup_run(tmp_path)

    def unavailable():
        raise ConnectionError("speech connection refused")

    assert run_pipeline(script, output, options, services=replace(services, speech_engine_factory=unavailable)) == 1
    assert "VoiceStudio" in read_json(output / "run-state.json")["steps"][3]["error"]["message"]

    def broken_render(*args):
        raise RuntimeError("render codec failed")

    assert run_pipeline(script, output, replace(options, resume=True), services=replace(services, renderer=broken_render)) == 1
    message = read_json(output / "run-state.json")["steps"][3]["error"]["message"]
    assert "render codec failed" in message
    assert "VoiceStudio" not in message
    assert message in capsys.readouterr().out
