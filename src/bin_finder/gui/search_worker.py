from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from bin_finder.models import SceneRecord
from bin_finder.search.service import DiscoveryService, SearchOptions


class SearchWorker(QThread):
    result_ready = pyqtSignal(object)
    failed = pyqtSignal(str, str)

    def __init__(self, service: DiscoveryService, scene: SceneRecord, options: SearchOptions):
        super().__init__()
        self.service = service
        self.scene = scene
        self.options = options

    def run(self) -> None:
        try:
            result = self.service.search_scene(self.scene, self.options)
        except Exception as exc:
            self.failed.emit(self.scene.scene_id, f"Tìm kiếm thất bại: {exc.__class__.__name__}")
            return
        self.result_ready.emit(result)
