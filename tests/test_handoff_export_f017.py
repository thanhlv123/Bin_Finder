"""F017 export integration: staging transaction, secrets, F015/F010 contracts, real FFmpeg."""
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from f017_support import export_package, load_handoff, make_inputs

import bin_finder.final_export as core
from bin_finder import handoff, handoff_smoke
from bin_finder.clips.extractor import FfmpegClipExtractor
from bin_finder.final_export import ExportOptions
from bin_finder.handoff import HANDOFF_FILENAME, verify_handoff_package


def test_handoff_is_opt_in_and_f015_output_unchanged(tmp_path):
    result = export_package(tmp_path, options=ExportOptions())
    assert result.handoff_path is None
    assert not (result.manifest_path.parent / HANDOFF_FILENAME).exists()


def test_handoff_created_in_staging_with_legacy_adapter_unchanged(tmp_path):
    result = export_package(tmp_path, options=ExportOptions(handoff=True, integration_adapter=True))
    package = result.manifest_path.parent
    assert result.handoff_path == package / HANDOFF_FILENAME
    adapter = json.loads(result.adapter_paths[0].read_text(encoding="utf-8"))
    assert adapter["format"] == "ai_video_editor_bin_finder_adapter_v1"
    assert [s["footage"]["source_start_seconds"] for s in adapter["scenes"]] == [0, 0, 0]
    data = load_handoff(package)
    assert data["format"] == "bin_finder_handoff_v1" and data["ready"] is True
    assert (data["scene_count"], data["clip_count"], data["total_duration_seconds"]) == (3, 3, 15)
    assert verify_handoff_package(package).clip_count == 3
    assert not list(package.glob("*.tmp"))


def test_handoff_failure_publishes_nothing(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("disk error")
    monkeypatch.setattr(core, "build_handoff", fail)
    scenes, clips = make_inputs(tmp_path)
    from types import SimpleNamespace
    from f017_support import FakeExtractor
    service = core.FinalExportService(FakeExtractor(), probe=SimpleNamespace(executable=""))
    result = service.export("f017", scenes, clips, tmp_path / "library", ExportOptions(handoff=True))
    assert result.status == "failed"
    assert not (tmp_path / "library").exists()
    assert not list(tmp_path.glob(".bin-finder-export-partial-*"))


def test_self_verification_failure_publishes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "verify_handoff_package",
                        lambda stage: (_ for _ in ()).throw(handoff.HandoffError("sha256-mismatch")))
    scenes, clips = make_inputs(tmp_path)
    from types import SimpleNamespace
    from f017_support import FakeExtractor
    service = core.FinalExportService(FakeExtractor(), probe=SimpleNamespace(executable=""))
    result = service.export("f017", scenes, clips, tmp_path / "library", ExportOptions(handoff=True))
    assert (result.status, result.error) == ("failed", "handoff-invalid")
    assert not (tmp_path / "library").exists()
    assert not list(tmp_path.glob(".bin-finder-export-partial-*"))


def test_not_ready_creates_no_handoff(tmp_path):
    from types import SimpleNamespace
    from f017_support import FakeExtractor
    scenes, clips = make_inputs(tmp_path)
    clips.pop()
    service = core.FinalExportService(FakeExtractor(), probe=SimpleNamespace(executable=""))
    result = service.export("f017", scenes, clips, tmp_path / "library", ExportOptions(handoff=True))
    assert result.status == "not_ready" and result.handoff_path is None
    assert not (tmp_path / "library").exists()


def test_no_secrets_signed_urls_or_developer_paths_in_handoff(tmp_path, monkeypatch):
    secret = "f017-test-only-secret-value"
    monkeypatch.setenv("BIN_FINDER_PEXELS_API_KEY", secret)
    scenes, clips = make_inputs(tmp_path)
    clips = [replace(c, title=secret, creator=secret, source_url="https://example.com/v?token=" + secret,
        source_metadata={**c.source_metadata, "Authorization": "Bearer " + secret,
            "raw_response": {"secret": secret}, "api_key": secret,
            "license_url": "https://example.com/license?signed=" + secret,
            "license_basis": "owned " + secret}) for c in clips]
    scenes = [replace(s, english_text="narration " + secret) for s in scenes]
    result = export_package(tmp_path, clips=clips, scenes=scenes)
    text = result.handoff_path.read_text(encoding="utf-8")
    for forbidden in (secret, "Authorization", "raw_response", "api_key", "?token=", "?signed=",
                      str(tmp_path), str(tmp_path).replace("\\", "/"), "\\\\"):
        assert forbidden not in text
    assert load_handoff(result.manifest_path.parent)["scenes"][0]["footage"]["provenance"][
        "license_url"] == "https://example.com/license"
    assert verify_handoff_package(result.manifest_path.parent).clip_count == 3


def test_metadata_disabled_omits_provenance_but_keeps_required_fields(tmp_path):
    result = export_package(tmp_path, options=ExportOptions(handoff=True, include_metadata=False))
    footage = load_handoff(result.manifest_path.parent)["scenes"][0]["footage"]
    assert "provenance" not in footage and "source_url" not in footage
    assert footage["rights_status"] == "owned" and footage["creator"] == "Fixture creator"
    assert verify_handoff_package(result.manifest_path.parent).clip_count == 3


def test_f010_not_rerun_on_materialized_coordinates(tmp_path, monkeypatch):
    calls = []
    original = core.evaluate_project
    monkeypatch.setattr(core, "evaluate_project", lambda p: calls.append(p) or original(p))
    result = export_package(tmp_path)
    assert len(calls) == 1 and [c.start for c in calls[0].selected_clips] == [10, 0, 30]
    assert [s["footage"]["original_source_start_seconds"]
            for s in load_handoff(result.manifest_path.parent)["scenes"]] == [10, 0, 30]


def test_smoke_requires_explicit_approval(monkeypatch, capsys):
    monkeypatch.setattr(handoff_smoke, "run_smoke", lambda: pytest.fail("unapproved smoke executed"))
    assert handoff_smoke.main([]) == 0
    assert capsys.readouterr().out.strip() == "SKIPPED_NOT_APPROVED"


def test_smoke_without_ffmpeg_is_not_a_pass(monkeypatch, capsys):
    from types import SimpleNamespace
    monkeypatch.setattr(handoff_smoke, "FfmpegClipExtractor", lambda **_: SimpleNamespace(executable=""))
    assert handoff_smoke.main(["--approve-test-export"]) == 2
    assert capsys.readouterr().out.strip() == "SKIPPED_NO_FFMPEG"


FFMPEG = FfmpegClipExtractor().executable


@pytest.mark.skipif(not FFMPEG or not shutil.which(FFMPEG), reason="FFmpeg unavailable for real handoff")
def test_real_ffmpeg_handoff_move_tamper_and_missing(tmp_path):
    handoff_smoke.run_chain(FFMPEG, tmp_path)
    assert not list(tmp_path.glob(".bin-finder-export-partial-*"))
