from PyQt6.QtCore import QThread, pyqtSignal

from bin_finder.acquisition import AcquisitionCancelled


class AcquisitionWorker(QThread):
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    progress = pyqtSignal(object, object)

    def __init__(self, service, request):
        super().__init__()
        self.service, self.request = service, request

    def run(self):
        try:
            result = self.service.acquire(
                self.request, progress=self.progress.emit,
                cancelled=self.isInterruptionRequested)
        except AcquisitionCancelled:
            self.cancelled.emit()
        except Exception:
            self.failed.emit("Tải footage thất bại.")
        else:
            self.result_ready.emit(result)
