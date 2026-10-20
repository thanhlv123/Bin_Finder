from dataclasses import replace

from PyQt6.QtCore import QEventLoop, QThread, QTimer
from PyQt6.QtWidgets import QApplication

from bin_finder.evaluation import ReviewStore
from bin_finder.gui.main_window import MainWindow
from bin_finder.workflow import WorkflowResult
from test_final_selection_f014 import make_item  # shared offline media/evidence fixture


APP = QApplication.instance() or QApplication([])


def wait_final(window):
    worker = window._final_worker
    assert worker is not None
    loop = QEventLoop()
    finished = []
    worker.finished.connect(lambda: finished.append(True))
    worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    # The window owns deleteLater(); do not access the C++ worker after finished.
    assert finished
    APP.processEvents()
    assert window._final_worker is None


def test_offline_gui_smoke_separates_candidate_and_final_approval(make_item, tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "_search_scene", lambda *args: None)
    monkeypatch.setattr(MainWindow, "_review_store", lambda self: ReviewStore(tmp_path / "reviews.json"))
    import bin_finder.final_selection as core
    fingerprint = core.fingerprint_file
    threads = []
    def checked_fingerprint(path):
        threads.append(QThread.currentThread())
        assert QThread.currentThread() != APP.thread()
        return fingerprint(path)
    scene, item = make_item()
    monkeypatch.setattr(core, "fingerprint_file", checked_fingerprint)
    window = MainWindow()
    assert window.final_button.text() == "Duyệt clip cuối"
    assert window.prepare_final_button.text() == "Chuẩn bị clip cuối"
    window.scenes = [replace(scene, target_duration=60)]
    window._current_scene = window.scenes[0]
    window.scene_panel.set_scenes(window.scenes)
    window.selected_panel.reset(1, window.scenes)
    window.review_panel.set_scene(window.scenes[0])
    window.export_panel.dest.setText(str(tmp_path / "export"))
    window.review_panel.set_candidate(item.candidate)
    assert not window.final_button.isEnabled()
    window._candidate_selected(item.candidate)
    assert window._review_store().decisions()[0].decision == "accepted"
    assert window.final_selections == ()
    assert window.selected_panel.ordered_scene_ids() == []
    window._workflow_complete(WorkflowResult((item,), tmp_path / "unused-workflow.json"))
    assert not window.final_selections
    assert not window.final_button.isEnabled()
    window._prepare_final()
    wait_final(window)
    assert window.final_button.isEnabled()
    assert not window.final_selections
    window.final_button.click()
    wait_final(window)
    assert len(window.final_selections) == 1
    assert window.final_selections[0].scene_id == scene.scene_id
    assert window.acceptance_report.ready
    assert window.selected_panel.ordered_scene_ids() == [scene.scene_id]
    assert window.export_panel.export.isEnabled()
    assert window._review_store().decisions()[0].decision == "accepted"
    assert not (tmp_path / "export").exists()
    assert threads
    window.close()
    window.deleteLater()
    APP.processEvents()


def test_pending_review_is_invalidated_by_candidate_change(make_item, tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "_search_scene", lambda *args: None)
    scene, item = make_item()
    window = MainWindow()
    window.scenes = [scene]
    window.review_panel.set_candidate(item.candidate)
    window._workflow_complete(WorkflowResult((item,), tmp_path / "unused.json"))
    window._prepare_final()
    # Change review context before any queued worker result reaches the GUI.
    window.search_panel.candidate_changed.emit(replace(item.candidate, candidate_id="different"))
    wait_final(window)
    assert not window.final_button.isEnabled()
    assert not window.final_selections
    window.close()
    window.deleteLater()
    APP.processEvents()


def test_preparation_without_valid_proposal_keeps_approval_disabled(make_item, tmp_path, monkeypatch):
    monkeypatch.setattr(MainWindow, "_search_scene", lambda *args: None)
    scene, item = make_item()
    window = MainWindow()
    window.scenes = [scene]
    window.review_panel.set_candidate(item.candidate)
    item.proposals = (replace(item.proposals[0], accepted=False),)
    window._workflow_complete(WorkflowResult((item,), tmp_path / "unused.json"))
    window._prepare_final()
    wait_final(window)
    assert not window.final_button.isEnabled()
    assert window.final_selections == ()
    window.close()
    window.deleteLater()
    APP.processEvents()
