"""F020: Panel 7 exposes the F017 portable handoff, independent of the legacy adapter."""
import json
from threading import Event

import pytest
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

import bin_finder.final_export as core
import bin_finder.gui.final_export_worker as worker_module
from bin_finder.acceptance import evaluate_project, production_acceptance_policy
from bin_finder.final_export import ExportOptions
from bin_finder.final_selection import build_final_project
from bin_finder.gui.main_window import MainWindow
from bin_finder.handoff import HANDOFF_FILENAME, verify_handoff_package
from test_final_export_f015 import fixture_export  # noqa: F401  (shared offline fixture)

APP = QApplication.instance() or QApplication([])
ADAPTER = "_ai_video_editor_bin_finder_adapter.json"


def wait_for(worker):
    finished = []
    worker.finished.connect(lambda: finished.append(True))
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(8000, loop.quit)
    if not finished:
        loop.exec()
    APP.processEvents()
    assert finished


class Spy:
    """Wraps the fixture service to record the options and result of each GUI export."""
    def __init__(self, service):
        self.service, self.options, self.results = service, [], []

    def export(self, *args, **kwargs):
        options = args[4] if len(args) > 4 else kwargs.get("options")
        self.options.append(options)
        result = self.service.export(*args, **kwargs)
        self.results.append(result)
        return result


def open_window(f, monkeypatch):
    spy = Spy(f.service)
    monkeypatch.setattr(worker_module, "FinalExportService", lambda: spy)
    monkeypatch.setattr(MainWindow, "_search_scene", lambda *args: None)
    window = MainWindow()
    window.scenes = f.scenes
    window.final_selections = tuple(f.clips)
    window.export_panel.dest.setText(str(f.destination))
    window._refresh_acceptance()
    return window, spy


def run_export(window):
    window._export_final()
    worker = window._export_worker
    assert worker is not None
    wait_for(worker)
    assert window._export_worker is None


def close(window):
    window.close()
    window.deleteLater()
    APP.processEvents()


def test_panel_has_dedicated_checked_handoff_option_and_core_default_unchanged(monkeypatch):
    monkeypatch.setattr(MainWindow, "_search_scene", lambda *args: None)
    window = MainWindow()
    try:
        panel = window.export_panel
        assert panel.handoff_option.text() == "Tạo gói handoff portable"
        assert panel.handoff_option.isChecked() and panel.handoff_option.isEnabled()
        assert "_bin_finder_handoff.json" in panel.handoff_option.toolTip()
        assert "bin_finder_handoff_v1" in panel.handoff_option.toolTip()
        assert not panel.adapter_option.isChecked()
        assert "ai_video_editor_bin_finder_adapter_v1" in panel.adapter_option.toolTip()
        assert panel.handoff_option is not panel.adapter_option
        assert panel.height() == 168  # accepted Panel 7 geometry unchanged
        assert ExportOptions().handoff is False  # F017 core stays opt-in
    finally:
        close(window)


@pytest.mark.parametrize("handoff,adapter", [(True, False), (False, True), (True, True), (False, False)])
def test_four_option_combinations_are_independent(fixture_export, monkeypatch, handoff, adapter):  # noqa: F811
    f = fixture_export
    window, spy = open_window(f, monkeypatch)
    try:
        window.export_panel.handoff_option.setChecked(handoff)
        window.export_panel.adapter_option.setChecked(adapter)
        run_export(window)
        options, result = spy.options[0], spy.results[0]
        assert (options.handoff, options.integration_adapter) == (handoff, adapter)
        assert result.status == "success", result.error
        assert (f.destination / HANDOFF_FILENAME).is_file() is handoff
        assert (f.destination / ADAPTER).is_file() is adapter
        assert (result.handoff_path is not None) is handoff
        assert (f.destination / "footage_manifest.json").is_file()
        status = window.export_panel.export_status.text()
        assert status == "Đã xuất footage" + (" · Handoff portable" if handoff else "")
        if handoff:
            assert result.handoff_path == f.destination / HANDOFF_FILENAME
            assert verify_handoff_package(f.destination).clip_count == 3
        if adapter:
            assert json.loads((f.destination / ADAPTER).read_text(encoding="utf-8"))["format"] == \
                "ai_video_editor_bin_finder_adapter_v1"
    finally:
        close(window)


def test_default_gui_export_package_verifies_and_survives_move(fixture_export, monkeypatch, tmp_path):  # noqa: F811
    f = fixture_export
    window, spy = open_window(f, monkeypatch)
    try:
        run_export(window)
        assert spy.options[0].handoff is True and spy.options[0].csv_index is True
        names = sorted(p.name for p in f.destination.iterdir())
        assert names == ["_bin_finder_handoff.json", "footage", "footage_index.csv",
                         "footage_manifest.json"]
        assert sorted(p.name for p in (f.destination / "footage").iterdir()) == [
            "scene_001.mp4", "scene_002.mp4", "scene_003.mp4"]
        assert verify_handoff_package(f.destination).clip_count == 3
        moved = tmp_path / "moved" / "renamed_package"
        moved.parent.mkdir()
        f.destination.rename(moved)
        assert verify_handoff_package(moved).clip_count == 3
    finally:
        close(window)


def test_handoff_failure_publishes_nothing_and_reports_failure(fixture_export, monkeypatch):  # noqa: F811
    f = fixture_export
    def fail(*args, **kwargs):
        raise OSError("disk error")
    monkeypatch.setattr(core, "build_handoff", fail)
    window, spy = open_window(f, monkeypatch)
    try:
        run_export(window)
        assert spy.results[0].status == "failed"
        assert window.export_panel.export_status.text() == "Xuất thất bại: export-failed"
        assert not f.destination.exists()
        assert not list(f.destination.parent.glob(".bin-finder-export-partial-*"))
    finally:
        close(window)


def test_unchecked_handoff_is_not_affected_by_handoff_failure(fixture_export, monkeypatch):  # noqa: F811
    f = fixture_export
    monkeypatch.setattr(core, "build_handoff", lambda *a, **k: pytest.fail("handoff was not requested"))
    window, spy = open_window(f, monkeypatch)
    try:
        window.export_panel.handoff_option.setChecked(False)
        run_export(window)
        assert spy.results[0].status == "success"
        assert not (f.destination / HANDOFF_FILENAME).exists()
    finally:
        close(window)


def test_cancelled_export_publishes_no_handoff(fixture_export, monkeypatch):  # noqa: F811
    f = fixture_export
    entered, release = Event(), Event()
    def bounded(*_):
        entered.set()
        assert release.wait(5)
    f.extractor.after_extract = bounded
    window, spy = open_window(f, monkeypatch)
    try:
        window._export_final()
        worker = window._export_worker
        finished = []
        worker.finished.connect(lambda: finished.append(True))
        assert entered.wait(2)
        window.export_panel.cancel_export.click()
        release.set()
        wait_for(worker)
        assert spy.results[0].status == "cancelled" and spy.results[0].handoff_path is None
        assert window.export_panel.export_status.text() == "Đã hủy xuất footage"
        assert not f.destination.exists()
        assert not list(f.destination.parent.glob(".bin-finder-export-partial-*"))
    finally:
        close(window)


def test_gui_long_form_and_legacy_policies_unchanged(fixture_export, monkeypatch):  # noqa: F811
    f = fixture_export
    window, _ = open_window(f, monkeypatch)
    try:
        assert window.acceptance_report == evaluate_project(
            build_final_project("CUBA_VIDEO_001", f.scenes, f.clips, f.destination),
            production_acceptance_policy())
        assert window.acceptance_report.ready
        assert evaluate_project(build_final_project("p", f.scenes, f.clips, f.destination)).ready
    finally:
        close(window)
