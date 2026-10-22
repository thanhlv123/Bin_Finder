"""F019: production long-form acceptance policy vs the unchanged legacy F010 default."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from f017_support import FakeExtractor
from PyQt6.QtWidgets import QApplication
from test_final_selection_f014 import make_item  # noqa: F401  (shared offline evidence fixture)

from bin_finder import handoff
from bin_finder.acceptance import AcceptancePolicy, evaluate_project, production_acceptance_policy
from bin_finder.final_export import ExportOptions, FinalExportService
from bin_finder.final_selection import (
    FinalSelectionService, build_final_project, handoff_final_project,
)
from bin_finder.gui.main_window import MainWindow
from bin_finder.handoff import verify_handoff_package
from bin_finder.integration_adapter import FORMAT as ADAPTER_FORMAT, IntegrationExportError
from bin_finder.models import FootageProject, SceneRecord, SelectedClipRecord

APP = QApplication.instance() or QApplication([])
PRODUCTION = production_acceptance_policy()


def make_project(count, seconds=5.0, *, files=None, score=0.9):
    """``count`` scenes of ``seconds`` each, every clip from its own source (clean rotation)."""
    scenes = [SceneRecord(f"scene_{i:03d}", i, f"Scene {i}", target_duration=seconds)
              for i in range(1, count + 1)]
    clips = [SelectedClipRecord(f"clip_{i:03d}", f"scene_{i:03d}", i, "local", f"source_{i:03d}",
        f"Clip {i}", str(files[i - 1]) if files else f"D:/clips/{i:03d}.mp4", 10.0, 10.0 + seconds,
        seconds, .9, .9, score, "owned") for i in range(1, count + 1)]
    return FootageProject("LONG_FORM", Path("D:/out"), scenes, clips)


def test_legacy_default_unchanged_60_to_180():
    policy = AcceptancePolicy()
    assert (policy.min_duration_seconds, policy.max_duration_seconds) == (60.0, 180.0)
    assert evaluate_project(make_project(12)).ready                     # exactly 60 s
    assert evaluate_project(make_project(36)).ready                     # exactly 180 s
    for count in (37, 60, 120):
        report = evaluate_project(make_project(count))
        assert not report.ready and report.duration_issue == "expected-duration-above-maximum"
    low = evaluate_project(make_project(11))
    assert not low.ready and low.duration_issue == "expected-duration-below-minimum"


def test_production_policy_definition():
    assert PRODUCTION == AcceptancePolicy(min_duration_seconds=60.0, max_duration_seconds=None,
        min_final_score=0.60, require_all_scenes=True, require_clean_rotation=True,
        require_no_overlap=True)
    assert AcceptancePolicy().max_duration_seconds == 180.0  # default object untouched
    PRODUCTION.validate()
    AcceptancePolicy(max_duration_seconds=None).validate()
    with pytest.raises(ValueError):
        AcceptancePolicy(min_duration_seconds=60, max_duration_seconds=30).validate()
    with pytest.raises(ValueError):
        evaluate_project(make_project(12), AcceptancePolicy(min_duration_seconds=-1))
    with pytest.raises(ValueError):
        evaluate_project(make_project(12), AcceptancePolicy(min_final_score=1.1))


@pytest.mark.parametrize("count,seconds", [(37, 185), (60, 300), (120, 600)])
def test_production_accepts_long_form_projects(count, seconds):
    project = make_project(count)
    report = evaluate_project(project, PRODUCTION)
    assert report.expected_duration_seconds == seconds
    assert report.ready and report.duration_issue == "" and report.coverage_ratio == 1.0
    legacy = evaluate_project(project)
    assert not legacy.ready and legacy.duration_issue == "expected-duration-above-maximum"


def test_production_still_rejects_short_projects_and_enforces_minimum():
    assert evaluate_project(make_project(12), PRODUCTION).ready
    report = evaluate_project(make_project(11), PRODUCTION)
    assert not report.ready and report.duration_issue == "expected-duration-below-minimum"


def test_production_keeps_every_other_gate():
    missing = make_project(60)
    missing.selected_clips.pop(5)
    report = evaluate_project(missing, PRODUCTION)
    assert not report.ready and report.unresolved_scene_ids == ("scene_006",)

    low = make_project(60)
    low.selected_clips[7] = replace(low.selected_clips[7], final_score=0.4)
    report = evaluate_project(low, PRODUCTION)
    assert not report.ready and report.low_score_scene_ids == ("scene_008",)

    rotation = make_project(60)
    rotation.selected_clips[10] = replace(rotation.selected_clips[10], source_id="source_010")
    assert evaluate_project(rotation, PRODUCTION).source_rotation_issues
    assert not evaluate_project(rotation, PRODUCTION).ready

    overlap = make_project(60)
    overlap.selected_clips[20] = replace(overlap.selected_clips[20], source_id="source_001",
                                         start=12.0, end=17.0)
    report = evaluate_project(overlap, PRODUCTION)
    assert report.overlap_issues and not report.ready

    empty = evaluate_project(FootageProject("EMPTY", Path("D:/out"), [], []), PRODUCTION)
    assert not empty.ready and empty.scene_count == 0


def files_for(directory, count):
    paths = []
    for i in range(count):
        path = directory / f"source_{i + 1:03d}.mp4"
        path.write_bytes(f"offline source {i}".encode())
        paths.append(path)
    return paths


def real_project(directory, count):
    paths = files_for(directory, count)
    from bin_finder.analysis.fingerprint import fingerprint_file
    project = make_project(count, files=paths)
    project.selected_clips = [replace(c, source_metadata={
        "media_sha256": fingerprint_file(c.local_file).sha256, "license_basis": "owned"})
        for c in project.selected_clips]
    return project


def exporter():
    return FinalExportService(FakeExtractor(), probe=SimpleNamespace(executable=""))


@pytest.mark.parametrize("count", [37, 60])
def test_final_export_is_not_blocked_by_duration_over_180(tmp_path, count):
    project = real_project(tmp_path, count)
    result = exporter().export("LONG_FORM", project.scenes, project.selected_clips,
                               tmp_path / "library", ExportOptions(handoff=True))
    assert result.status == "success", result.error
    assert result.readiness.ready and result.readiness.expected_duration_seconds == count * 5
    assert result.exported_count == count and result.total_duration == count * 5
    assert verify_handoff_package(tmp_path / "library").clip_count == count


def test_final_export_still_blocks_under_minimum_and_other_gates(tmp_path):
    short = real_project(tmp_path, 11)
    result = exporter().export("S", short.scenes, short.selected_clips, tmp_path / "short")
    assert result.status == "not_ready"
    assert result.readiness.duration_issue == "expected-duration-below-minimum"
    assert not (tmp_path / "short").exists()
    partial = real_project(tmp_path, 60)
    partial.selected_clips.pop()
    result = exporter().export("P", partial.scenes, partial.selected_clips, tmp_path / "partial")
    assert result.status == "not_ready" and result.readiness.unresolved_scene_ids
    assert not (tmp_path / "partial").exists()


def gui(monkeypatch, project, destination):
    monkeypatch.setattr(MainWindow, "_search_scene", lambda *args: None)
    window = MainWindow()
    window.project_panel.project_name.setText("LONG_FORM")
    window.scenes = list(project.scenes)
    window.final_selections = tuple(project.selected_clips)
    window.export_panel.dest.setText(str(destination))
    window._refresh_acceptance()
    return window


def test_gui_readiness_uses_production_policy_and_enables_export(monkeypatch, tmp_path):
    project = real_project(tmp_path, 60)
    window = gui(monkeypatch, project, tmp_path / "library")
    try:
        report = window.acceptance_report
        assert report.ready and report.expected_duration_seconds == 300
        assert window.export_panel.export.isEnabled()
        assert "Sẵn sàng xuất" in window.export_panel.title_label.text()
        # Same inputs, same verdict as FinalExportService.
        result = exporter().export("LONG_FORM", project.scenes, project.selected_clips,
                                   tmp_path / "library", ExportOptions())
        assert result.status == "success" and result.readiness == report
    finally:
        window.close()


def test_gui_still_blocks_short_and_incomplete_projects(monkeypatch, tmp_path):
    short = gui(monkeypatch, make_project(11), tmp_path / "a")
    try:
        assert not short.acceptance_report.ready and not short.export_panel.export.isEnabled()
        assert short.acceptance_report.duration_issue == "expected-duration-below-minimum"
    finally:
        short.close()
    project = make_project(60)
    project.selected_clips.pop()
    incomplete = gui(monkeypatch, project, tmp_path / "b")
    try:
        assert not incomplete.acceptance_report.ready
        assert not incomplete.export_panel.export.isEnabled()
    finally:
        incomplete.close()


def test_direct_f010_handoff_path_stays_legacy(tmp_path):
    project = make_project(37)
    with pytest.raises(IntegrationExportError):
        handoff_final_project("LEGACY", project.scenes, project.selected_clips, tmp_path / "pkg")
    assert not (tmp_path / "pkg").exists() or not list((tmp_path / "pkg").iterdir())
    ok = make_project(12)
    paths = handoff_final_project("LEGACY", ok.scenes, ok.selected_clips, tmp_path / "ok")
    assert Path(paths[0]).name == "_ai_video_editor_bin_finder_adapter.json"
    assert ADAPTER_FORMAT == "ai_video_editor_bin_finder_adapter_v1"


def test_f014_approval_and_f017_schema_unchanged(make_item):  # noqa: F811
    scene, item = make_item()
    service = FinalSelectionService()
    option = service.options(scene, item)[0]
    assert not service.approve(scene, item, option.clip_id, [scene]).accepted
    assert service.approve(scene, item, option.clip_id, [scene], human_approved=True).accepted
    assert handoff.FORMAT == "bin_finder_handoff_v1"
    assert handoff.TOP_KEYS == {"format", "producer", "project_id", "ready", "scene_count",
        "clip_count", "total_duration_seconds", "manifest_relative_path", "manifest_sha256", "scenes"}
    assert "max_duration_seconds" not in handoff.TOP_KEYS | handoff.FOOTAGE_KEYS
    assert build_final_project("p", [scene], [], Path("D:/out")).selected_clips == []
