"""BF-S03B opt-in one-video pilot: offline and fake-response acceptance."""
from __future__ import annotations

from bin_finder.search.slot_local_vision_smoke import main
from bin_finder.search.slot_local_vision_bridge import (
    LocalVisionAssessment, LocalVisionRun,
)
from bin_finder.verification.models import VerificationDimensions

import pytest


def _params(tmp_path):
    clip = tmp_path / "one.mp4"
    clip.write_bytes(b"existing-local-video-fixture; never decoded")
    return ["--video", str(clip), "--allowed-root", str(tmp_path),
            "--start", "0", "--end", "4"]


def test_offline_default_zero_calls_and_no_paths(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    assert "BFS03B_STATUS: no-manual-media-selected" in out
    assert "BFS03B_MODEL_CALLS: 0" in out
    assert "BFS03B_PROVIDER_CALLS: 0" in out
    assert "BFS03B_CLOUD_IMAGE_UPLOADS: 0" in out


def test_nominated_file_without_any_opt_in_never_inspects(tmp_path, capsys):
    missing = tmp_path / "missing.mp4"
    assert main([
        "--video", str(missing), "--allowed-root", str(tmp_path),
    ]) == 0
    output = capsys.readouterr().out
    assert "BFS03B_LOCAL_GATE: manual-opt-in-required" in output
    assert "BFS03B_MODEL_CALLS: 0" in output
    assert str(missing) not in output


def test_local_inspection_does_not_imply_ollama_permission(tmp_path, capsys, monkeypatch):
    params = _params(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("No VLM allowed")
    monkeypatch.setattr(
        "bin_finder.search.slot_local_vision_smoke.verify_local_vision",
        forbidden,
    )
    assert main(params + ["--approve-local-inspection"]) == 0
    output = capsys.readouterr().out
    assert "BFS03B_LOCAL_GATE: local-ready-for-inference-approval" in output
    assert "BFS03B_STATUS: local-inference-approval-required" in output
    assert "BFS03B_MODEL_CALLS: 0" in output


def test_second_flag_cannot_bypass_first(capsys):
    with pytest.raises(SystemExit) as err:
        main(["--approve-local-inference"])
    assert err.value.code == 2
    assert "requires both explicit opt-ins" in capsys.readouterr().err


def test_one_local_clip_fake_vision_result_is_unverified(tmp_path, capsys, monkeypatch):
    params = _params(tmp_path)
    calls = []
    def fake_bridge(plan, gate, *, approve_local_inference, config):
        calls.append((plan, gate, approve_local_inference, config))
        return LocalVisionRun(
            slot_id=gate.slot_id, status="human-review-required",
            assessments=(
                LocalVisionAssessment(
                    slot_id=gate.slot_id, provider="local",
                    source_id="local:manual-single",
                    status="vision-provisional-human-review",
                    dimensions=VerificationDimensions(
                        subject_match=.8, action_match=None, time_match=None,
                        context_conflict=.1,
                    ), confidence=.72,
                    reasons=("action-not-assessed",),
                ),
            ),
            attempted_model_calls=1,
        )
    monkeypatch.setattr(
        "bin_finder.search.slot_local_vision_smoke.verify_local_vision",
        fake_bridge,
    )
    assert main(params + [
        "--approve-local-inspection", "--approve-local-inference"
    ]) == 0
    out = capsys.readouterr().out
    assert len(calls) == 1 and calls[0][2] is True
    assert calls[0][3].url == "http://127.0.0.1:11434"
    assert calls[0][3].frames == 3
    assert "BFS03B_MODEL_CALLS: 1" in out
    assert "BFS03B_SUBJECT: 0.8000" in out
    assert "BFS03B_ACTION: unknown" in out
    assert "BFS03B_TIME: unknown" in out
    assert "BFS03B_LICENSE_OR_TIMELINE_APPROVED: False" in out
    assert "BFS03B_HUMAN_REVIEW_REQUIRED: True" in out
    assert "BFS03B_FINAL: UNVERIFIED_HUMAN_PLAYBACK_REQUIRED" in out
    assert str(tmp_path) not in out


def test_nonexistent_file_with_both_approvals_does_not_call_model(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("Model must not run on invalid source")
    monkeypatch.setattr(
        "bin_finder.search.slot_local_vision_smoke.verify_local_vision",
        forbidden,
    )
    assert main([
        "--video", str(tmp_path / "missing.mp4"),
        "--allowed-root", str(tmp_path),
        "--approve-local-inspection", "--approve-local-inference",
    ]) == 0
    assert "BFS03B_STATUS: no-safe-local-media" in capsys.readouterr().out


def test_no_remote_video_uri_is_read_even_with_approvals(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("No model or provider calls on remote URL")
    monkeypatch.setattr(
        "bin_finder.search.slot_local_vision_smoke.verify_local_vision",
        forbidden,
    )
    assert main([
        "--video", "https://cdn.example.org/a.mp4?token=PRIVATE",
        "--allowed-root", str(tmp_path),
        "--approve-local-inspection", "--approve-local-inference",
    ]) == 0
    out = capsys.readouterr().out
    assert "BFS03B_STATUS: no-safe-local-media" in out
    assert "PRIVATE" not in out and "https://" not in out
