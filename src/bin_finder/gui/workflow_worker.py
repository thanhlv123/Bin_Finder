from PyQt6.QtCore import QThread, pyqtSignal


class WorkflowWorker(QThread):
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()
    progress = pyqtSignal(object)

    def __init__(self, service, request):
        super().__init__()
        self.service, self.request = service, request

    def run(self):
        try:
            result = self.service.run(self.request, progress=self.progress.emit,
                                      cancelled=self.isInterruptionRequested)
        except Exception:
            self.failed.emit("Xử lý tư liệu thất bại.")
            return
        # Always deliver the structured report, including partial/cancelled work.
        self.result_ready.emit(result)
        if result.cancelled:
            self.cancelled.emit()
