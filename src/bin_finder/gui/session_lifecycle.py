"""F016 GUI persistence adapter: store snapshots, never restore implicit approval."""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from bin_finder.session_codec import FORMAT, SessionError, scene_to_data, selection_to_data
from bin_finder.session_recovery import restore_session
from bin_finder.session_store import SessionStore, SessionStoreError


class SessionLifecycle:
    def __init__(self, window):
        self.window = window
        self.store = SessionStore()
        self.project_id = window.project_panel.project_name.text()
        self.failed = False
        self.unresolved_rows = []
        self.timer = QTimer(window)
        self.timer.setSingleShot(True)
        self.timer.setInterval(600)
        self.timer.timeout.connect(self.save)
        self.restore()
        window.project_panel.script.textChanged.connect(self.schedule)
        window.project_panel.output_dir.textChanged.connect(self.schedule)
        window.export_panel.dest.textChanged.connect(self.schedule)

    def schedule(self, *_):
        if not self.window._session_restoring:
            self.failed = False
            self.timer.start()

    def save(self, *, project_id=None):
        if self.window._session_restoring or self.failed:
            return False
        w = self.window
        try:
            payload = {
                "format": FORMAT,
                "project_id": project_id if project_id is not None else w.project_panel.project_name.text(),
                "scenes": [scene_to_data(scene) for scene in w.scenes],
                "final_selections": [selection_to_data(clip) for clip in w.final_selections],
                "workflow_refs": [],
                "ui_state": {
                    "script_text": w.project_panel.script.toPlainText(),
                    "output_dir": w.export_panel.dest.text(),
                    "current_scene_id": w._current_scene.scene_id,
                },
            }
            # Keep prior explicit-approval evidence for unresolved media without
            # putting it back into the GUI's approved selection collection.
            if payload["project_id"] == self.project_id:
                selected = {row["scene_id"] for row in payload["final_selections"]}
                scene_ids = {scene.scene_id for scene in w.scenes}
                payload["final_selections"].extend(
                    row for row in self.unresolved_rows
                    if row["scene_id"] in scene_ids and row["scene_id"] not in selected
                )
            self.store.save(payload)
            return True
        except (SessionError, SessionStoreError, OSError, TypeError, ValueError):
            w.workflow_status.setText("Không thể lưu phiên; dữ liệu trước đó được giữ")
            return False

    def restore(self):
        w = self.window
        try:
            payload = self.store.load_active()
            if payload is None:
                return
            restored = restore_session(payload)
            if not restored.scenes:
                raise SessionError("empty-session")
        except (SessionError, SessionStoreError, OSError, TypeError, ValueError):
            self.failed = True
            w.workflow_status.setText("Phiên không hợp lệ; không tự ghi đè")
            return
        unresolved_ids = {scene_id for scene_id, _reason in restored.unresolved}
        self.unresolved_rows = [
            row for row in payload["final_selections"] if row["scene_id"] in unresolved_ids
        ]
        w._session_restoring = True
        try:
            w.project_panel.project_name.setText(restored.project_id)
            w.project_panel.script.setPlainText(restored.ui_state.get("script_text", ""))
            output = restored.ui_state.get("output_dir", "")
            if output:
                w.project_panel.output_dir.setText(output)
                w.export_panel.dest.setText(output)
            w.scenes = list(restored.scenes)
            w.final_selections = restored.final_selections
            w.workflow_results.clear()
            w._clear_final_options()
            w.scene_panel.set_scenes(w.scenes)
            w.selected_panel.set_final_clips(w.final_selections, w.scenes)
            for clip in w.final_selections:
                w.scene_panel.mark_selected(clip.scene_id)
            selected_id = restored.ui_state.get("current_scene_id", "")
            index = next((i for i, scene in enumerate(w.scenes)
                          if scene.scene_id == selected_id), 0)
            w._current_scene = w.scenes[index]
            w.scene_panel.list.setCurrentRow(index)
            w.review_panel.set_scene(w._current_scene)
            self.project_id = restored.project_id
            w._refresh_acceptance()
            if restored.unresolved:
                w.workflow_status.setText(
                    f"Khôi phục: {len(restored.unresolved)} clip cần duyệt lại")
            else:
                w.workflow_status.setText("Đã khôi phục phiên; kiểm tra trước khi xuất")
        finally:
            w._session_restoring = False

    def project_changed(self):
        if self.window._session_restoring:
            return False
        self.timer.stop()
        if self.project_id:
            self.save(project_id=self.project_id)
        self.project_id = self.window.project_panel.project_name.text()
        self.unresolved_rows = []
        self.schedule()
        return True

    def invalidate_unresolved(self):
        # A newly split script is a different approval context even with reused IDs.
        self.unresolved_rows = []

    def close(self):
        self.timer.stop()
        self.save()
