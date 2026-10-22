"""F016 GUI restart regressions for validated final approval and READY gating."""
from dataclasses import replace

from PyQt6.QtWidgets import QApplication

from bin_finder.gui import main_window, session_lifecycle as gui_session
from bin_finder.session_codec import scene_from_data
from bin_finder.session_store import SessionStore
from test_session_final_recovery_f016 import approved_clip
from test_session_recovery_f016 import sample


APP = QApplication.instance() or QApplication([])


def new_window(monkeypatch, root):
    monkeypatch.setattr(main_window.MainWindow, "_search_scene", lambda *args: None)
    monkeypatch.setattr(gui_session, "SessionStore", lambda: SessionStore(root))
    return main_window.MainWindow()


def close_window(window):
    window.close()
    window.deleteLater()
    APP.processEvents()


def test_gui_restart_restores_approved_clip_and_recomputes_ready(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    media = tmp_path / "owned.mp4"
    clip = approved_clip(media)
    scene = replace(scene_from_data(sample()["scenes"][0]), target_duration=60.0)
    first = new_window(monkeypatch, root)
    first.project_panel.project_name.setText("F016-GUI-TEST")
    first.project_panel.script.setPlainText("Saved narrative")
    first.scenes = [scene]
    first._current_scene = scene
    first.scene_panel.set_scenes([scene])
    first.final_selections = (clip,)
    first.selected_panel.set_final_clips((clip,), [scene])
    first.export_panel.dest.setText(str(tmp_path / "exports"))
    assert first._session_lifecycle.save()
    close_window(first)

    second = new_window(monkeypatch, root)
    assert second.project_panel.project_name.text() == "F016-GUI-TEST"
    assert second.project_panel.script.toPlainText() == "Saved narrative"
    assert second.scenes == [scene]
    assert len(second.final_selections) == 1
    assert second.final_selections[0].clip_id == clip.clip_id
    assert second.final_selections[0].source_url == ""
    assert "raw_provider_response" not in second.final_selections[0].source_metadata
    assert second.selected_panel.ordered_scene_ids() == ["scene_001"]
    assert second.acceptance_report.ready
    assert second.export_panel.export.isEnabled()
    close_window(second)


def test_gui_missing_media_never_restores_approval_or_ready(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    media = tmp_path / "owned.mp4"
    clip = approved_clip(media)
    scene = replace(scene_from_data(sample()["scenes"][0]), target_duration=60.0)
    first = new_window(monkeypatch, root)
    first.scenes = [scene]
    first._current_scene = scene
    first.final_selections = (clip,)
    assert first._session_lifecycle.save()
    close_window(first)
    media.unlink()

    second = new_window(monkeypatch, root)
    assert second.final_selections == ()
    assert second.selected_panel.ordered_scene_ids() == []
    assert not second.acceptance_report.ready
    assert not second.export_panel.export.isEnabled()
    assert "cần duyệt lại" in second.workflow_status.text()
    close_window(second)


def test_corrupt_session_not_overwritten_by_demo_on_close(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    store = SessionStore(root)
    path = store.save(sample())
    path.write_bytes(b'{"format":"bad"}')
    original = path.read_bytes()
    window = new_window(monkeypatch, root)
    assert window._session_lifecycle.failed
    assert window.final_selections == ()
    close_window(window)
    assert path.read_bytes() == original


def test_candidate_review_does_not_become_final_approval(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    first = new_window(monkeypatch, root)
    assert first._session_lifecycle.save()
    close_window(first)
    second = new_window(monkeypatch, root)
    assert second.final_selections == ()
    assert second.selected_panel.ordered_scene_ids() == []
    assert not second.export_panel.export.isEnabled()
    close_window(second)
