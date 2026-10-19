from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QEventLoop, QObject, QThread, QTimer, pyqtSlot
from PyQt6.QtWidgets import QApplication

from bin_finder.acquisition import AcquisitionCancelled
from bin_finder.gui.acquisition_worker import AcquisitionWorker


APP = QApplication.instance() or QApplication([])


class Receiver(QObject):
    def __init__(self):
        super().__init__()
        self.results, self.threads = [], []

    @pyqtSlot(object)
    @pyqtSlot(str)
    def receive(self, value):
        self.results.append(value)
        self.threads.append(QThread.currentThread())


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_worker_signals_are_delivered_on_gui_thread(outcome):
    receiver = Receiver()
    events = []
    def acquire(request, *, progress, cancelled):
        assert QThread.currentThread() != APP.thread()
        progress(1, 2)
        if outcome == "failure":
            raise OSError("private-credential")
        if outcome == "cancel":
            # Interruption requested while running, never QThread.terminate().
            QThread.currentThread().requestInterruption()
            assert cancelled()
            raise AcquisitionCancelled("cancelled")
        return "verified-result"
    worker = AcquisitionWorker(SimpleNamespace(acquire=acquire), object())
    worker.result_ready.connect(receiver.receive)
    worker.failed.connect(receiver.receive)
    worker.cancelled.connect(lambda: events.append("cancelled"))
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(3000, loop.quit)
    worker.start()
    loop.exec()
    assert worker.wait(3000)
    APP.processEvents()
    if outcome == "cancel":
        assert events == ["cancelled"] and not receiver.results
    else:
        assert receiver.threads == [APP.thread()]
        assert len(receiver.results) == 1
        assert "private-credential" not in receiver.results[0]
        assert receiver.results[0] == ("verified-result" if outcome == "success" else "Tải footage thất bại.")
    worker.deleteLater()
    receiver.deleteLater()
    APP.processEvents()
