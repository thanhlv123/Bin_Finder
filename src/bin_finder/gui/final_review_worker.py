"""All final media checks, including approval-time hashing, run off the GUI thread."""
from PyQt6.QtCore import QThread, pyqtSignal

from bin_finder.final_selection import FinalSelectionService


class FinalReviewWorker(QThread):
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, scene, item, scenes, selections, clip_id=None):
        super().__init__()
        self.scene, self.item = scene, item
        self.scenes, self.selections, self.clip_id = tuple(scenes), tuple(selections), clip_id

    def run(self):
        try:
            service = FinalSelectionService()
            if self.clip_id is None:
                prepared = service.prepare(self.scene, self.item)
                result = (prepared, service.options(self.scene, prepared))
            else:
                result = service.approve(self.scene, self.item, self.clip_id,
                    self.scenes, self.selections, human_approved=True)
            self.result_ready.emit(result)
        except Exception:
            self.failed.emit("Clip chưa sẵn sàng")
