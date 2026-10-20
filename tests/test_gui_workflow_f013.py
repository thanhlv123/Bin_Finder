from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEventLoop, QObject, QThread, QTimer, pyqtSlot
from PyQt6.QtWidgets import QApplication

from bin_finder.gui.workflow_worker import WorkflowWorker
from bin_finder.workflow import WorkflowProgress


APP = QApplication.instance() or QApplication([])


class Receiver(QObject):
    def __init__(self):
        super().__init__()
        self.values, self.threads = [], []

    @pyqtSlot(object)
    @pyqtSlot(str)
    def receive(self, value):
        self.values.append(value)
        self.threads.append(QThread.currentThread())


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_worker_signals_and_progress_on_gui_thread(outcome):
    receiver, progress_receiver = Receiver(), Receiver()
    cancellations = []
    report = SimpleNamespace(cancelled=outcome == "cancel", items=())
    def run(request, *, progress, cancelled):
        assert QThread.currentThread() != APP.thread()
        progress(WorkflowProgress(1, 1, "s", "c", "analyzing"))
        if outcome == "failure":
            raise OSError("Authorization: private-credential")
        if outcome == "cancel":
            QThread.currentThread().requestInterruption()
            assert cancelled()
        return report
    worker = WorkflowWorker(SimpleNamespace(run=run), object())
    worker.result_ready.connect(receiver.receive)
    worker.failed.connect(receiver.receive)
    worker.progress.connect(progress_receiver.receive)
    worker.cancelled.connect(lambda: cancellations.append(True))
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(3000, loop.quit)
    worker.start()
    loop.exec()
    assert worker.wait(3000)
    APP.processEvents()
    assert receiver.threads == [APP.thread()]
    assert progress_receiver.threads == [APP.thread()]
    assert progress_receiver.values[0].stage == "analyzing"
    assert cancellations == ([True] if outcome == "cancel" else [])
    assert receiver.values == (["Xử lý tư liệu thất bại."] if outcome == "failure" else [report])
    worker.deleteLater()
    receiver.deleteLater()
    progress_receiver.deleteLater()
    APP.processEvents()


def test_window_workflow_controls_preserve_selection_and_review(tmp_path, monkeypatch):
    from bin_finder.gui.main_window import MainWindow
    from bin_finder.evaluation import ReviewStore
    from bin_finder.models import CandidateRecord
    from bin_finder.workflow import WorkflowResult, WorkflowItemResult
    monkeypatch.setattr(MainWindow, "_search_scene", lambda *args: None)
    monkeypatch.setattr(MainWindow, "_review_store", lambda self: ReviewStore(tmp_path / "reviews.json"))
    window = MainWindow()
    assert window.workflow_button.text() == "Tải và phân tích tư liệu đã duyệt"
    assert not window.cancel_workflow_button.isEnabled()
    candidate = CandidateRecord("c", window.scenes[0].scene_id, "pexels", "pexels:7", "ocean", 6, .8)
    window.review_panel.set_candidate(candidate)
    window._workflow_complete(WorkflowResult((WorkflowItemResult(candidate, stage="analyzed"),),
                                            tmp_path / "workflow.json"))
    assert len(window.workflow_results) == 1
    assert not window._review_store().decisions()
    window.close()
    window.deleteLater()
    APP.processEvents()
