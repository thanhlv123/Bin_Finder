from threading import Event

from PyQt6.QtCore import QEventLoop, QThread, QTimer
from PyQt6.QtWidgets import QApplication

from bin_finder.gui.main_window import MainWindow
from bin_finder.gui.final_export_worker import FinalExportWorker
from bin_finder.final_export import ExportOptions
from test_final_export_f015 import fixture_export

APP = QApplication.instance() or QApplication([])


def wait_worker(worker, finished):
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    if not finished:
        loop.exec()
    APP.processEvents()
    assert finished


def window_for(f, monkeypatch):
    monkeypatch.setattr(MainWindow, "_search_scene", lambda *args: None)
    window = MainWindow()
    window.scenes = f.scenes
    window.final_selections = tuple(f.clips)
    window.export_panel.dest.setText(str(f.destination))
    window._refresh_acceptance()
    return window


def test_gui_ready_only_explicit_export_success_and_queued_progress(fixture_export, monkeypatch):
    f = fixture_export
    import bin_finder.gui.final_export_worker as module
    monkeypatch.setattr(module, "FinalExportService", lambda: f.service)
    worker_threads, gui_threads, progress = [], [], []
    f.extractor.after_extract = lambda *_: worker_threads.append(QThread.currentThread())
    original_progress = MainWindow._export_progress
    def observe_progress(self, value):
        gui_threads.append(QThread.currentThread())
        progress.append(value)
        original_progress(self, value)
    monkeypatch.setattr(MainWindow, "_export_progress", observe_progress)
    window = window_for(f, monkeypatch)
    try:
        assert window.acceptance_report.ready and window.export_panel.export.isEnabled()
        assert not f.destination.exists()  # becoming READY never exports automatically
        assert window.export_panel.export.text() == "⇩  Xuất footage đã chọn"
        assert window.export_panel.export_options[0].isChecked()
        assert not window.export_panel.export_options[0].isEnabled()
        assert not window.export_panel.export_options[2].isEnabled()
        assert not window.export_panel.adapter_option.isChecked()
        window.export_panel.export.click()
        worker = window._export_worker
        assert worker is not None and not window.export_panel.export.isEnabled()
        finished = []
        worker.finished.connect(lambda: finished.append(True))
        wait_worker(worker, finished)
        assert worker_threads and all(t != APP.thread() for t in worker_threads)
        assert progress and all(t == APP.thread() for t in gui_threads)
        assert progress[-1].completed == 3 and progress[-1].scene_id == "scene_003"
        assert window.export_panel.export_status.text() == "Đã xuất footage · Handoff portable"  # F020 GUI default
        assert window._export_worker is None and not window.export_panel.cancel_export.isEnabled()
        assert (f.destination / "footage_manifest.json").is_file()
    finally:
        window.close()
        window.deleteLater()
        APP.processEvents()


def test_gui_not_ready_button_and_handler_cannot_export(fixture_export, monkeypatch):
    f = fixture_export
    f.clips.pop()
    window = window_for(f, monkeypatch)
    try:
        assert not window.export_panel.export.isEnabled()
        window._export_final()
        assert window._export_worker is None and not f.destination.exists()
    finally:
        window.close()
        window.deleteLater()


def test_gui_failure_delivered(fixture_export, monkeypatch):
    f = fixture_export
    import bin_finder.gui.final_export_worker as module
    monkeypatch.setattr(module, "FinalExportService", lambda: f.service)
    f.sources["A"].unlink()
    window = window_for(f, monkeypatch)
    window._export_final()
    worker = window._export_worker
    finished = []
    worker.finished.connect(lambda: finished.append(True))
    wait_worker(worker, finished)
    assert window.export_panel.export_status.text() == "Xuất thất bại: source-not-regular"
    assert window._export_worker is None and not f.destination.exists()
    window.close()
    window.deleteLater()


def test_gui_cancellation_waits_for_current_clip_and_defers_close(fixture_export, monkeypatch):
    f = fixture_export
    import bin_finder.gui.final_export_worker as module
    monkeypatch.setattr(module, "FinalExportService", lambda: f.service)
    entered, release = Event(), Event()
    def bounded_extraction(*_):
        entered.set()
        assert release.wait(5)
    f.extractor.after_extract = bounded_extraction
    window = window_for(f, monkeypatch)
    window._export_final()
    worker = window._export_worker
    finished = []
    worker.finished.connect(lambda: finished.append(True))
    assert entered.wait(2)
    window._refresh_acceptance()
    assert not window.export_panel.export.isEnabled()
    window.export_panel.cancel_export.click()
    assert worker.isInterruptionRequested() and worker.isRunning()
    assert window.close() is False
    # The current extraction finishes normally; cancellation schedules no next clip.
    release.set()
    wait_worker(worker, finished)
    assert len(f.extractor.calls) == 1 and not f.destination.exists()
    assert window.export_panel.export_status.text() == "Đã hủy xuất footage"
    assert window._export_worker is None
    assert not list(f.destination.parent.glob(".bin-finder-export-partial-*"))
    window.close()
    window.deleteLater()


def test_worker_unexpected_failure_signal_contains_no_sensitive_exception(fixture_export, monkeypatch):
    import bin_finder.gui.final_export_worker as module
    class BrokenService:
        def export(self, *args, **kwargs):
            raise RuntimeError("sensitive exception contents")
    monkeypatch.setattr(module, "FinalExportService", BrokenService)
    f = fixture_export
    worker = FinalExportWorker("test", f.scenes, f.clips, f.destination, ExportOptions())
    errors, finished = [], []
    worker.failed.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.start()
    wait_worker(worker, finished)
    assert errors == ["Không thể xuất footage"]
    assert not f.destination.exists()
    worker.deleteLater()
