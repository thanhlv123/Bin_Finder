"""ZB-03A standalone PyQt6 *research* timeline review UI.

This window NEVER changes Bin Finder main GUI or F014 approvals, does not call
providers, import selected clips into production, play video, or render/export.
Synthetic thumbnails are labels, NOT frames from real videos.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from bin_finder.draft_timeline import (
    DraftTimeline, DraftTimelineError, local_candidate_for_path,
)
from bin_finder.models import SceneRecord
from bin_finder.visual_plan_audit import audit_visual_story_plan
from bin_finder.visual_planning import VisualStoryPlan


_STATUS = {
    "missing": "Chưa có ứng viên",
    "proposed": "Chờ kiểm duyệt",
    "reviewed": "Đã kiểm tra bố cục",
    "locked": "Đã khóa bố cục",
    "needs_editorial_resolution": "Cần quyết định biên tập",
}
_COLORS = {
    "missing": "#b91c1c",
    "proposed": "#b45309",
    "reviewed": "#15803d",
    "locked": "#0369a1",
    "needs_editorial_resolution": "#b45309",
}
_STRATEGY = {
    "search": "FOOTAGE ĐỀ XUẤT",
    "hold": "GIỮ SHOT TRƯỚC",
    "transition": "CHUYỂN Ý",
    "graphic": "ĐỒ HỌA CẦN XÁC MINH",
}


def _label(text: str, size: int = 12) -> QLabel:
    item = QLabel(text)
    item.setWordWrap(True)
    item.setStyleSheet(f"font-size:{size}px;")
    return item


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        child = item.widget()
        if child is not None:
            child.setParent(None)
            child.deleteLater()


class TimelineReviewWindow(QMainWindow):
    """In-memory storyboard editor; approvals here are layout-only."""
    def __init__(self, scenes: tuple[SceneRecord, ...],
                 plan: VisualStoryPlan, draft: DraftTimeline):
        super().__init__()
        self._scenes = tuple(scenes)
        self._plan = plan
        self.draft = draft
        self.active_shot_id = draft.items[0].shot_id
        self.audit = audit_visual_story_plan(plan, scenes)
        self.setWindowTitle("Bin Finder — ZB-03A Timeline Review (Research)")
        self.resize(1280, 820)
        self._build()
        self._refresh()

    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setSpacing(8)
        header = _label(
            "ZB-03A | TIMELINE KIỂM DUYỆT (BẢN NGHIÊN CỨU)\n"
            "Chưa phát video · chưa xác minh bản quyền · không xuất bản dựng",
            14,
        )
        header.setStyleSheet(
            "background:#14243a;color:white;border-radius:6px;"
            "padding:12px;font-weight:bold;"
        )
        page.addWidget(header)

        upper = QSplitter(Qt.Orientation.Horizontal)
        page.addWidget(upper, 5)

        scenes_column = QWidget()
        left = QVBoxLayout(scenes_column)
        left.addWidget(_label("Lời thuyết minh / Narration", 14))
        self.scene_list = QListWidget()
        self.scene_list.setObjectName("zb03a_narration_list")
        for scene in self._scenes:
            row = QListWidgetItem(
                f"{scene.order:02d} | {scene.target_duration:.1f}s\n{scene.english_text}"
            )
            row.setData(Qt.ItemDataRole.UserRole, scene.scene_id)
            self.scene_list.addItem(row)
        self.scene_list.currentItemChanged.connect(self._narration_changed)
        left.addWidget(self.scene_list)
        upper.addWidget(scenes_column)

        review_column = QWidget()
        review = QVBoxLayout(review_column)
        self.active_title = _label("", 15)
        self.active_title.setObjectName("zb03a_shot_details")
        review.addWidget(self.active_title)
        self.active_status = _label("")
        review.addWidget(self.active_status)

        preview = QFrame()
        preview.setMinimumHeight(145)
        preview.setStyleSheet("background:#1f2937;border-radius:8px;color:white;")
        preview_layout = QVBoxLayout(preview)
        self.preview_text = _label(
            "MINH HỌA VỊ TRÍ CLIP\n03A chưa phát video hoặc lấy thumbnail thật",
            13,
        )
        self.preview_text.setStyleSheet("color:white;")
        self.preview_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_layout.addWidget(self.preview_text)
        review.addWidget(preview)

        review.addWidget(_label("Ứng viên cho shot được chọn", 13))
        self.candidate_list = QListWidget()
        self.candidate_list.setObjectName("zb03a_candidate_list")
        self.candidate_list.setMinimumHeight(90)
        review.addWidget(self.candidate_list)

        row1 = QHBoxLayout()
        self.choose_button = QPushButton("Thay bằng ứng viên đã chọn")
        self.choose_button.clicked.connect(self._choose_candidate)
        row1.addWidget(self.choose_button)
        self.local_button = QPushButton("Chọn video trên máy…")
        self.local_button.clicked.connect(self._add_local_video)
        row1.addWidget(self.local_button)
        review.addLayout(row1)

        row2 = QHBoxLayout()
        self.review_button = QPushButton("Đã kiểm tra bố cục")
        self.review_button.clicked.connect(self._mark_reviewed)
        row2.addWidget(self.review_button)
        self.lock_button = QPushButton("Khóa bố cục")
        self.lock_button.clicked.connect(self._toggle_lock)
        row2.addWidget(self.lock_button)
        review.addLayout(row2)

        review.addWidget(_label("Ghi chú cho người biên tập (chỉ trong phiên)", 12))
        self.note = QPlainTextEdit()
        self.note.setMaximumHeight(55)
        self.note.setObjectName("zb03a_note")
        review.addWidget(self.note)
        self.save_note_button = QPushButton("Lưu ghi chú vào bản nháp")
        self.save_note_button.clicked.connect(self._save_note)
        review.addWidget(self.save_note_button)
        upper.addWidget(review_column)
        upper.setSizes([420, 780])

        page.addWidget(_label("VIDEO TRACK — vị trí theo lời thoại ước tính; chưa phải thời gian cắt video", 13))
        self.timeline_scroll = QScrollArea()
        self.timeline_scroll.setWidgetResizable(True)
        self.timeline_scroll.setMinimumHeight(183)
        track_container = QWidget()
        self.video_track = QHBoxLayout(track_container)
        self.video_track.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.timeline_scroll.setWidget(track_container)
        page.addWidget(self.timeline_scroll, 2)

        page.addWidget(_label("NARRATION TRACK — thứ tự scene gốc", 12))
        self.narration_track_scroll = QScrollArea()
        self.narration_track_scroll.setWidgetResizable(True)
        self.narration_track_scroll.setMinimumHeight(100)
        voice_container = QWidget()
        voice = QHBoxLayout(voice_container)
        voice.setAlignment(Qt.AlignmentFlag.AlignLeft)
        for scene in self._scenes:
            cell = QFrame()
            cell.setFixedWidth(215)
            cell.setStyleSheet(
                "background:#e8edf4;border:1px solid #ced6e0;"
                "border-radius:5px;"
            )
            content = QVBoxLayout(cell)
            content.addWidget(_label(
                f"{scene.scene_id} · ~{scene.target_duration:.1f}s", 11
            ))
            speech = _label(scene.english_text, 11)
            speech.setMaximumHeight(56)
            content.addWidget(speech)
            voice.addWidget(cell)
        self.narration_track_scroll.setWidget(voice_container)
        page.addWidget(self.narration_track_scroll, 1)

        self.info = _label("", 11)
        self.info.setObjectName("zb03a_summary")
        self.info.setStyleSheet("color:#374151;")
        page.addWidget(self.info)

    def _refresh(self) -> None:
        _clear(self.video_track)
        for item in self.draft.items:
            selected = item.shot_id == self.active_shot_id
            color = _COLORS[item.review_status]
            card = QPushButton()
            card.setObjectName("zb03a_shot_" + item.shot_id)
            card.setFixedWidth(max(180, 145 * len(item.scene_ids)))
            card.setMinimumHeight(132)
            card.setText(
                f"{item.shot_id.upper()}  |  {_STRATEGY[item.strategy]}\n"
                f"{item.narration_start_estimate:.1f}–"
                f"{item.narration_end_estimate:.1f}s*\n"
                f"{item.visual_goal[:66]}\n"
                f"{_STATUS[item.review_status]}"
            )
            card.setToolTip(
                "Khoảng thời gian VO ước tính, không phải vị trí clip đã dựng"
            )
            card.setStyleSheet(
                f"background:{'#eaf3ff' if selected else '#f8fafc'};"
                f"border:2px solid {color};border-radius:7px;"
                "padding:7px;text-align:left;"
                "color:#111827;font-size:11px;"
            )
            card.clicked.connect(
                lambda checked=False, shot_id=item.shot_id:
                self.select_shot(shot_id)
            )
            self.video_track.addWidget(card)
        active = self.draft.item(self.active_shot_id)
        self.active_title.setText(
            f"{active.shot_id} · {_STRATEGY[active.strategy]}\n"
            f"{active.visual_goal}"
        )
        issues = [
            flag.code for flag in self.audit.flags
            if active.shot_id == flag.shot_id
        ]
        self.active_status.setText(
            f"{_STATUS[active.review_status]} — "
            f"scene: {', '.join(active.scene_ids)}"
            + (f"\nCảnh báo: {', '.join(issues)}" if issues else "")
        )
        self.candidate_list.clear()
        for candidate in active.candidates:
            prefix = "✓ " if active.selected_candidate_id == candidate.candidate_id else ""
            row = QListWidgetItem(
                f"{prefix}{candidate.title}  ·  "
                f"{'File local chưa xác minh' if candidate.origin == 'local' else 'Mẫu giả lập'}"
            )
            row.setData(Qt.ItemDataRole.UserRole, candidate.candidate_id)
            self.candidate_list.addItem(row)
            if candidate.candidate_id == active.selected_candidate_id:
                self.candidate_list.setCurrentItem(row)
        label = next(
            (c.title for c in active.candidates
             if c.candidate_id == active.selected_candidate_id),
            "Chưa có clip cụ thể",
        )
        self.preview_text.setText(
            f"{label}\n"
            "THUMBNAIL MINH HỌA — CHƯA CÓ PREVIEW VIDEO THẬT"
        )
        self.note.setPlainText(active.note)
        editable = active.strategy == "search" and not active.locked
        self.choose_button.setEnabled(editable and bool(active.candidates))
        self.local_button.setEnabled(editable)
        self.review_button.setEnabled(
            editable and active.selected_candidate_id is not None
        )
        self.lock_button.setEnabled(
            active.locked or (active.strategy == "search" and active.reviewed)
        )
        self.lock_button.setText("Mở khóa" if active.locked else "Khóa bố cục")
        self.note.setReadOnly(active.locked)
        self.save_note_button.setEnabled(not active.locked)
        counts = self.draft.counts()
        self.info.setText(
            f"Shot: {len(self.draft.items)} | "
            f"Chờ duyệt: {counts['proposed']} | "
            f"Đã xem: {counts['reviewed']} | "
            f"Khóa: {counts['locked']} | "
            f"Cần quyết định: {counts['needs_editorial_resolution']} | "
            "Không phải F014 approval. * Chỉ là thời gian lời thoại ước tính."
        )

    def select_shot(self, shot_id: str) -> None:
        self.draft.item(shot_id)  # raise immediately for incorrect requests
        self.active_shot_id = shot_id
        self._refresh()

    def _narration_changed(self, current, _previous):
        if current is None:
            return
        scene_id = current.data(Qt.ItemDataRole.UserRole)
        for item in self.draft.items:
            if scene_id in item.scene_ids:
                self.select_shot(item.shot_id)
                break

    def _apply(self, operation) -> None:
        try:
            self.draft = operation()
        except DraftTimelineError as exc:
            QMessageBox.warning(self, "ZB-03A Review", str(exc))
            return
        self._refresh()

    def _choose_candidate(self) -> None:
        row = self.candidate_list.currentItem()
        if row is not None:
            candidate_id = row.data(Qt.ItemDataRole.UserRole)
            self._apply(lambda: self.draft.choose(self.active_shot_id, candidate_id))

    def _mark_reviewed(self) -> None:
        self._apply(lambda: self.draft.mark_reviewed(self.active_shot_id))

    def _toggle_lock(self) -> None:
        item = self.draft.item(self.active_shot_id)
        self._apply(lambda: self.draft.set_lock(item.shot_id, not item.locked))

    def _save_note(self) -> None:
        self._apply(lambda: self.draft.set_note(
            self.active_shot_id, self.note.toPlainText()
        ))

    def _add_local_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn video local (chưa xác minh)",
            "", "Video (*.mp4 *.mkv *.mov *.webm)"
        )
        if not path:
            return
        try:
            candidate = local_candidate_for_path(path)
            current = self.draft.item(self.active_shot_id)
            existing = next(
                (c for c in current.candidates if c.candidate_id == candidate.candidate_id),
                None,
            )
            updated = (self.draft if existing else self.draft.add_candidate(
                self.active_shot_id, candidate
            ))
            self.draft = updated.choose(self.active_shot_id, candidate.candidate_id)
        except DraftTimelineError as exc:
            QMessageBox.warning(self, "ZB-03A Review", str(exc))
            return
        self._refresh()
