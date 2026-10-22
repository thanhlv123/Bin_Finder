"""F016 end-to-end: restored session -> revalidation -> F010 READY -> real F015 export."""
import json
import shutil

import pytest
from PyQt6.QtWidgets import QApplication

from bin_finder import session_export_smoke as smoke
from bin_finder.clips.extractor import FfmpegClipExtractor
from bin_finder.gui import main_window, session_lifecycle as gui_session
from bin_finder.session_store import SessionStore

APP = QApplication.instance() or QApplication([])
FFMPEG = FfmpegClipExtractor().executable
pytestmark = pytest.mark.skipif(not FFMPEG or not shutil.which(FFMPEG),
                                reason="FFmpeg unavailable for real export")


def test_restore_ready_real_f015_export_and_tamper_refusal(tmp_path):
    result = smoke.run_chain(FFMPEG, tmp_path)
    assert result.status == "success"
    assert not list(tmp_path.glob(".bin-finder-export-partial-*"))


def test_gui_restart_restores_ready_and_exports_with_real_ffmpeg(tmp_path, monkeypatch):
    store, _scenes, selections = smoke.save_fixture_session(FFMPEG, tmp_path)
    monkeypatch.setattr(main_window.MainWindow, "_search_scene", lambda *args: None)
    monkeypatch.setattr(gui_session, "SessionStore", lambda: SessionStore(store.root))
    window = main_window.MainWindow()
    try:
        assert window.project_panel.project_name.text() == smoke.PROJECT_ID
        assert [c.clip_id for c in window.final_selections] == [c.clip_id for c in selections]
        # READY is recomputed from revalidated selections, never deserialized.
        assert window.acceptance_report.ready
        assert window.export_panel.export.isEnabled()
        destination = tmp_path / "library"
        assert window.export_panel.dest.text() == str(destination)
        window.export_panel.adapter_option.setChecked(True)
        window._export_final()
        worker = window._export_worker
        assert worker is not None
        assert worker.wait(120000)
        APP.processEvents()
        assert window.export_panel.export_status.text() == "Đã xuất footage"
        manifest = json.loads((destination / "footage_manifest.json").read_text(encoding="utf-8"))
        assert manifest["readiness"]["ready"]
        assert [r["original_source_start_seconds"] for r in manifest["clips"]] == [10, 0, 30]
    finally:
        window.close()
        window.deleteLater()
        APP.processEvents()
