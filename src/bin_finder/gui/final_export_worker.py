"""Cooperative export worker; the current bounded FFmpeg call finishes safely."""
from PyQt6.QtCore import QThread, pyqtSignal

from bin_finder.final_export import FinalExportService


class FinalExportWorker(QThread):
    progress = pyqtSignal(object)
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, project_id, scenes, selections, destination, options):
        super().__init__()
        self.arguments = (project_id, tuple(scenes), tuple(selections), destination, options)

    def run(self):
        try:
            result = FinalExportService().export(*self.arguments,
                progress=self.progress.emit, cancelled=self.isInterruptionRequested)
            self.result_ready.emit(result)
        except Exception:
            self.failed.emit("Không thể xuất footage")
