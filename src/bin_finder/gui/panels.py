from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from bin_finder.demo_data import demo_candidates
from bin_finder.models import CandidateRecord, FootageProject, SceneRecord, SelectedClipRecord
from bin_finder.selection_state import SceneSelectionIndex
from bin_finder.gui.theme import PANEL_ACCENTS


def _duration_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _panel_title(number: int, title: str) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    badge = QLabel(str(number))
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    badge.setFixedSize(28, 28)
    badge.setStyleSheet(
        f"background:{PANEL_ACCENTS[number]}; color:white; border-radius:7px; font-weight:800; font-size:15px;"
    )
    text = QLabel(title)
    text.setObjectName("panelTitle")
    layout.addWidget(badge)
    layout.addWidget(text)
    layout.addStretch(1)
    return row


def make_thumb(label: str, width: int = 220, height: int = 116) -> QPixmap:
    pix = QPixmap(width, height)
    pix.fill(QColor("#172b3d"))
    painter = QPainter(pix)
    painter.setPen(QColor("#90bddf"))
    painter.drawRect(0, 0, width - 1, height - 1)
    painter.setPen(QColor("#f0f6fb"))
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, label[:42])
    painter.end()
    return pix


class Panel(QFrame):
    def __init__(self, number: int, title: str):
        super().__init__()
        self.setObjectName("panel")
        self.setStyleSheet(
            f"QFrame#panel {{ border: 2px solid {PANEL_ACCENTS[number]}; border-radius: 10px; background:#0b1623; }}"
        )
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(10, 9, 10, 10)
        self.body.setSpacing(8)

        title_row = QWidget()
        title_layout = QHBoxLayout(title_row)
        title_layout.setContentsMargins(0, 0, 0, 0)
        badge = QLabel(str(number))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(28, 28)
        badge.setStyleSheet(
            f"background:{PANEL_ACCENTS[number]}; color:white; border-radius:7px; font-weight:800; font-size:15px;"
        )
        self.title_label = QLabel(title)
        self.title_label.setObjectName("panelTitle")
        title_layout.addWidget(badge)
        title_layout.addWidget(self.title_label)
        title_layout.addStretch(1)
        self.body.addWidget(title_row)


class ProjectPanel(Panel):
    split_requested = pyqtSignal(str)

    def __init__(self):
        super().__init__(1, "Dự án & Kịch bản")
        form = QGridLayout()
        self.project_name = QLineEdit("CUBA_VIDEO_001")
        self.output_dir = QLineEdit(r"D:\FootageLibrary\CUBA_VIDEO_001")
        browse = QPushButton("Chọn...")
        browse.clicked.connect(self._choose_dir)
        form.addWidget(QLabel("Tên dự án"), 0, 0)
        form.addWidget(self.project_name, 0, 1, 1, 2)
        form.addWidget(QLabel("Thư mục lưu footage"), 1, 0)
        form.addWidget(self.output_dir, 1, 1)
        form.addWidget(browse, 1, 2)
        self.body.addLayout(form)

        self.body.addWidget(QLabel("Nhập kịch bản"))
        actions = QHBoxLayout()
        paste = QPushButton("Dán text")
        load = QPushButton("Tải file TXT")
        sample = QPushButton("Dùng kịch bản mẫu")
        paste.clicked.connect(lambda: self.script.setFocus())
        load.clicked.connect(self._load_txt)
        sample.clicked.connect(self._sample)
        for button in (paste, load, sample):
            actions.addWidget(button)
        self.body.addLayout(actions)

        self.script = QPlainTextEdit()
        self.script.setPlainText(
            "At dawn in Havana, an elderly Cuban mechanic repairs a faded 1955 Chevrolet while his "
            "granddaughter stands beside him holding an airline ticket and a packed suitcase."
        )
        self.script.setMinimumHeight(115)
        self.body.addWidget(self.script)
        split = QPushButton("✦  Chia cảnh tự động (AI)")
        split.setObjectName("primary")
        split.clicked.connect(lambda: self.split_requested.emit(self.script.toPlainText()))
        self.body.addWidget(split)

    def _choose_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu footage")
        if folder:
            self.output_dir.setText(folder)

    def _load_txt(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Tải kịch bản", "", "Text (*.txt);;All Files (*)")
        if filename:
            self.script.setPlainText(Path(filename).read_text(encoding="utf-8", errors="ignore"))

    def _sample(self):
        self.script.setPlainText(
            "At dawn in Havana, an elderly Cuban mechanic repairs a faded 1955 Chevrolet while his "
            "granddaughter stands beside him holding an airline ticket and a packed suitcase."
        )


class SourcePanel(Panel):
    def __init__(self):
        super().__init__(3, "Tùy chọn tìm kiếm & nguồn")

        providers = QHBoxLayout()
        providers.addWidget(QLabel("Nguồn"))
        for name in ("YouTube", "Storyblocks", "Pexels", "Pixabay", "Báo điện tử", "Thư viện local"):
            cb = QCheckBox(name)
            cb.setChecked(name not in ("Báo điện tử", "Thư viện local"))
            cb.setObjectName("providerCheck")
            providers.addWidget(cb)
        providers.addStretch(1)
        self.body.addLayout(providers)

        filters = QGridLayout()
        filters.setHorizontalSpacing(8)
        for col, (label, values) in enumerate(
            [
                ("Độ dài video", ["Tất cả", "< 4 phút", "4–20 phút", "> 20 phút"]),
                ("Độ phân giải", ["Tất cả (>=720p)", "1080p+", "4K"]),
                ("Hướng video", ["Tất cả", "16:9", "9:16", "1:1"]),
                ("Ngày đăng", ["Tất cả", "7 ngày", "30 ngày", "1 năm"]),
            ]
        ):
            filters.addWidget(QLabel(label), 0, col)
            combo = QComboBox()
            combo.addItems(values)
            filters.addWidget(combo, 1, col)
        self.body.addLayout(filters)

        types = QHBoxLayout()
        types.addWidget(QLabel("Loại nội dung"))
        for name in ("Video thực tế", "Video stock", "Tin tức", "Tài liệu", "Khác"):
            cb = QCheckBox(name)
            cb.setChecked(name != "Khác")
            types.addWidget(cb)
        types.addStretch(1)
        self.body.addLayout(types)

        rights = QHBoxLayout()
        rights.addWidget(QLabel("Chế độ bản quyền"))
        for name, checked in (
            ("Creative Commons", True),
            ("Commercial (Storyblocks)", False),
            ("Editorial", False),
            ("Public Domain", False),
        ):
            cb = QCheckBox(name)
            cb.setChecked(checked)
            rights.addWidget(cb)
        rights.addStretch(1)
        self.body.addLayout(rights)

        advanced = QHBoxLayout()
        for name in ("Dùng AI tạo nhiều query", "Phân tích ngữ cảnh cảnh", "Tìm cảnh tương tự"):
            advanced.addWidget(QPushButton(name))
        advanced.addStretch(1)
        advanced.addWidget(QLabel("Số kết quả / cảnh"))
        spin = QSpinBox()
        spin.setRange(5, 100)
        spin.setValue(20)
        advanced.addWidget(spin)
        self.body.addLayout(advanced)


class SceneListPanel(Panel):
    scene_changed = pyqtSignal(object)

    def __init__(self, scenes: list[SceneRecord]):
        super().__init__(2, f"Danh sách cảnh trong kịch bản ({len(scenes)} cảnh)")
        self._selected_scene_ids: set[str] = {
            scene.scene_id for scene in scenes if scene.status == "selected"
        }
        self._scenes: list[SceneRecord] = []
        self.list = QListWidget()
        self.list.setMinimumWidth(300)
        self.body.addWidget(self.list, 1)
        self.set_scenes(scenes)
        self.list.currentItemChanged.connect(self._emit_scene)
        add = QPushButton("＋ Thêm cảnh")
        self.body.addWidget(add)

    def _item_text(self, scene: SceneRecord) -> str:
        selected = scene.scene_id in self._selected_scene_ids
        suffix = "● Đã chọn" if selected else "● Chưa chọn"
        clipped = scene.english_text[:52] + ("…" if len(scene.english_text) > 52 else "")
        return f"{scene.order:02d}    {clipped}\n       {scene.target_duration:.1f}s     {suffix}"

    def set_scenes(self, scenes: list[SceneRecord]):
        incoming_ids = {scene.scene_id for scene in scenes}
        self._selected_scene_ids = {
            scene_id for scene_id in self._selected_scene_ids if scene_id in incoming_ids
        }
        self._selected_scene_ids.update(
            scene.scene_id for scene in scenes if scene.status == "selected"
        )
        self._scenes = list(scenes)
        self.list.clear()
        for scene in scenes:
            item = QListWidgetItem(self._item_text(scene))
            item.setData(Qt.ItemDataRole.UserRole, scene)
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint().__class__(280, 66)))
            self.list.addItem(item)
        if self.list.count():
            self.list.setCurrentRow(0)

    def mark_selected(self, scene_id: str):
        self._selected_scene_ids.add(scene_id)
        for index in range(self.list.count()):
            item = self.list.item(index)
            scene = item.data(Qt.ItemDataRole.UserRole)
            if scene and scene.scene_id == scene_id:
                item.setText(self._item_text(scene))
                break

    def _emit_scene(self, current, _previous):
        if current:
            self.scene_changed.emit(current.data(Qt.ItemDataRole.UserRole))


class AspectRatioPreview(QLabel):
    """Preview label that always shows the complete frame without cropping."""

    def __init__(self, text: str = ""):
        super().__init__(text)
        self._source_pixmap = QPixmap()

    def set_preview_pixmap(self, pixmap: QPixmap):
        self._source_pixmap = QPixmap(pixmap)
        self.setText("")
        self._refresh_pixmap()

    def clear_preview(self, text: str):
        self._source_pixmap = QPixmap()
        self.clear()
        self.setText(text)

    def _refresh_pixmap(self):
        if self._source_pixmap.isNull() or self.width() <= 1 or self.height() <= 1:
            return
        scaled = self._source_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        super().setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_pixmap()


class CandidateCard(QFrame):
    clicked = pyqtSignal(object)

    def __init__(self, candidate: CandidateRecord):
        super().__init__()
        self.candidate = candidate
        self.setToolTip(f"{candidate.creator}\n{candidate.source_url}")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet("QFrame {background:#0b1a29; border:1px solid #1d3b55; border-radius:8px;} QFrame:hover{border-color:#23a4ff;}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 7)
        thumb = QLabel()
        thumb.setPixmap(make_thumb(candidate.title, 240, 118))
        thumb.setScaledContents(True)
        thumb.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        thumb.setMinimumHeight(95)
        thumb.setMaximumHeight(135)
        layout.addWidget(thumb)
        meta = QHBoxLayout()
        source = QLabel(candidate.provider.title())
        source.setStyleSheet("font-weight:800; color:#45e7c2;")
        score = QLabel(f"{candidate.score:.2f}")
        score.setStyleSheet("font-weight:800; color:#39e8c2; font-size:15px;")
        meta.addWidget(source)
        meta.addStretch(1)
        meta.addWidget(QLabel(_duration_text(candidate.duration)))
        meta.addWidget(score)
        layout.addLayout(meta)
        title = QLabel(candidate.title)
        title.setWordWrap(True)
        title.setMinimumHeight(38)
        layout.addWidget(title)
        tags = QLabel(f"{candidate.rights_status}   {candidate.resolution}")
        tags.setObjectName("muted")
        layout.addWidget(tags)

    def mousePressEvent(self, event):
        self.clicked.emit(self.candidate)
        super().mousePressEvent(event)


class SearchResultsPanel(Panel):
    candidate_changed = pyqtSignal(object)

    def __init__(self, scene_id: str):
        super().__init__(4, "Kết quả tìm kiếm cho cảnh 01 (20 kết quả)")
        self._scene_id = scene_id
        tools = QHBoxLayout()
        tools.addWidget(QLabel("Sắp xếp theo:"))
        sort = QComboBox()
        sort.addItems(["Điểm phù hợp (cao → thấp)", "Nguồn", "Độ dài"])
        tools.addWidget(sort)
        tools.addStretch(1)
        source = QComboBox()
        source.addItems(["Nguồn: Tất cả", "YouTube", "Storyblocks", "Pexels", "Pixabay", "News", "Local"])
        tools.addWidget(source)
        tools.addWidget(QPushButton("↻ Tìm kiếm lại"))
        self.body.addLayout(tools)

        hint = QLabel("Click vào một kết quả để xem trước và đánh giá ở khung 5.")
        hint.setObjectName("muted")
        self.body.addWidget(hint)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(8)
        self._columns = 3
        for column in range(self._columns):
            self.grid.setColumnStretch(column, 1)
        self.scroll.setWidget(self.container)
        self.body.addWidget(self.scroll, 1)
        self.set_scene(scene_id)

    def set_scene(self, scene_id: str):
        self._scene_id = scene_id
        try:
            scene_order = int(scene_id.rsplit("_", 1)[-1])
        except (TypeError, ValueError):
            scene_order = 0

        candidates = demo_candidates(scene_id)
        self.title_label.setText(
            f"Kết quả tìm kiếm cho cảnh {scene_order:02d} ({len(candidates)} kết quả demo)"
        )

        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, candidate in enumerate(candidates):
            card = CandidateCard(candidate)
            card.clicked.connect(self.candidate_changed.emit)
            self.grid.addWidget(card, index // self._columns, index % self._columns)

        # Always bring the first row into view when the user changes scene.
        self.scroll.verticalScrollBar().setValue(0)


class ReviewPanel(Panel):
    select_candidate = pyqtSignal(object)
    waitlist_candidate = pyqtSignal(object)
    reject_candidate = pyqtSignal(object)
    compare_candidate = pyqtSignal(object)

    def __init__(self, scene: SceneRecord):
        super().__init__(5, "Xem, phân tích & đánh giá cảnh (Scene 01 / 24)")
        self.body.setSpacing(4)
        self.body.setContentsMargins(8, 7, 8, 7)
        self.scene = scene
        self.candidate: CandidateRecord | None = None

        nav = QHBoxLayout()
        nav.addWidget(QLabel("Cảnh:"))
        self.scene_combo = QComboBox()
        self.scene_combo.addItem("01 / 24")
        nav.addWidget(self.scene_combo, 1)
        nav.addWidget(QPushButton("‹"))
        nav.addWidget(QPushButton("›"))
        self.body.addLayout(nav)

        # The scene text/analysis area is tab-driven so only one content block is
        # visible at a time. This leaves substantially more room for each text box
        # and keeps the video preview visible regardless of the selected tab.
        self.analysis_tabs = QTabWidget()
        self.analysis_tabs.setObjectName("analysisTabs")
        self.original_tab = QWidget()
        self.vietnamese_tab = QWidget()
        self.keyword_tab = QWidget()
        self.object_tab = QWidget()
        self.avoid_tab = QWidget()
        self.source_tab = QWidget()
        self.analysis_tabs.addTab(self.original_tab, "Nội dung gốc")
        self.analysis_tabs.addTab(self.vietnamese_tab, "Tiếng Việt")
        self.analysis_tabs.addTab(self.keyword_tab, "Từ khóa")
        self.analysis_tabs.addTab(self.object_tab, "Đối tượng")
        self.analysis_tabs.addTab(self.avoid_tab, "Điều cần tránh")
        self.analysis_tabs.addTab(self.source_tab, "Gợi ý nguồn")
        self.analysis_tabs.setFixedHeight(112)
        self.analysis_tabs.tabBar().setUsesScrollButtons(True)
        self.analysis_tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.body.addWidget(self.analysis_tabs)

        self._build_text_tabs()
        self._build_context_tabs()
        self._build_preview_area()
        self.set_scene(self.scene)
        self.analysis_tabs.setCurrentIndex(1)

    def _build_text_tabs(self):
        original_layout = QVBoxLayout(self.original_tab)
        original_layout.setContentsMargins(6, 6, 6, 6)
        original_layout.setSpacing(5)
        original_layout.addWidget(QLabel("Nội dung tiếng Anh (gốc)"))
        self.en = QPlainTextEdit()
        self.en.setReadOnly(True)
        self.en.setObjectName("sceneText")
        self.en.setMinimumHeight(70)
        original_layout.addWidget(self.en, 1)

        vietnamese_layout = QVBoxLayout(self.vietnamese_tab)
        vietnamese_layout.setContentsMargins(6, 6, 6, 6)
        vietnamese_layout.setSpacing(5)
        vietnamese_layout.addWidget(QLabel("Nội dung tiếng Việt (dịch)"))
        self.vi = QPlainTextEdit()
        self.vi.setReadOnly(True)
        self.vi.setObjectName("sceneText")
        self.vi.setMinimumHeight(70)
        vietnamese_layout.addWidget(self.vi, 1)

    def _build_preview_area(self):
        self.video = AspectRatioPreview("PREVIEW VIDEO\nChọn một candidate ở khung 4")
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setFixedHeight(280)
        # Ignore pixmap size hints so preview content never pushes the right
        # workspace wider or changes the panel 5/7 geometry.
        self.video.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.video.setStyleSheet(
            "background:#07101a; border:1px solid #334d63; border-radius:8px; "
            "font-size:20px; color:#91aabe;"
        )
        self.body.addWidget(self.video, 3)

        self.candidate_title = QLabel("Chưa chọn candidate")
        self.candidate_title.setWordWrap(True)
        self.candidate_title.setFixedHeight(28)
        self.candidate_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.candidate_title.setStyleSheet("font-weight:700; font-size:14px;")
        self.body.addWidget(self.candidate_title)
        self.candidate_meta = QLabel("Nguồn · thời lượng · quyền sử dụng · điểm phù hợp")
        self.candidate_meta.setObjectName("muted")
        self.candidate_meta.setWordWrap(False)
        self.candidate_meta.setFixedHeight(20)
        self.candidate_meta.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.body.addWidget(self.candidate_meta)

        detail = QTabWidget()
        info = QLabel("Thông tin nguồn và metadata sẽ hiển thị tại đây.")
        info.setWordWrap(True)
        transcript = QLabel("Transcript theo timestamp sẽ hiển thị tại đây.")
        transcript.setWordWrap(True)
        shots = QLabel(
            "07:10–07:15   Mechanic opens the hood\n"
            "07:15–07:20   Close-up of engine repair\n"
            "07:20–07:25   Granddaughter nearby with suitcase"
        )
        shots.setWordWrap(True)
        ai = QLabel("AI verification: subject / action / location / object / conflict")
        ai.setWordWrap(True)
        fit = QLabel("Semantic score + VLM score + source diversity + rights score")
        fit.setWordWrap(True)
        for widget, title in (
            (info, "Thông tin"),
            (transcript, "Transcript"),
            (shots, "Các đoạn cảnh (Shot)"),
            (ai, "Đánh giá AI"),
            (fit, "Độ phù hợp"),
        ):
            box = QWidget()
            lay = QVBoxLayout(box)
            lay.addWidget(widget)
            lay.addStretch(1)
            detail.addTab(box, title)
        detail.setFixedHeight(84)
        self.body.addWidget(detail)

        actions = QHBoxLayout()
        actions.setSpacing(5)
        self.choose = QPushButton("✓ Chọn (~5s)")
        self.choose.setObjectName("primary")
        self.choose.setEnabled(False)
        self.choose.clicked.connect(lambda: self.select_candidate.emit(self.candidate))
        self.waitlist = QPushButton("⏳ Chờ")
        self.waitlist.setEnabled(False)
        self.waitlist.clicked.connect(lambda: self.waitlist_candidate.emit(self.candidate))
        self.reject = QPushButton("✕ Loại")
        self.reject.setEnabled(False)
        self.reject.clicked.connect(lambda: self.reject_candidate.emit(self.candidate))
        self.compare = QPushButton("A/B")
        self.compare.setEnabled(False)
        self.compare.clicked.connect(lambda: self.compare_candidate.emit(self.candidate))
        actions.addWidget(self.choose, 2)
        actions.addWidget(self.waitlist, 1)
        actions.addWidget(self.reject, 1)
        actions.addWidget(self.compare, 1)
        self.body.addLayout(actions)

    def _tag_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(False)
        label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        label.setStyleSheet(
            "background:#12304a; color:#e8f4ff; border:1px solid #2b5877; "
            "border-radius:10px; padding:5px 9px;"
        )
        return label

    def _tag_grid(self, values: tuple[str, ...], columns: int = 3) -> QWidget:
        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        if not values:
            empty = QLabel("Chưa có dữ liệu phân tích.")
            empty.setObjectName("muted")
            grid.addWidget(empty, 0, 0, 1, columns)
            return widget
        for index, value in enumerate(values):
            grid.addWidget(self._tag_label(value), index // columns, index % columns)
        for column in range(columns):
            grid.setColumnStretch(column, 0)
        grid.setColumnStretch(columns, 1)
        grid.setRowStretch((len(values) - 1) // columns + 1, 1)
        return widget

    def _chips(self, values: tuple[str, ...]) -> QWidget:
        # Keyword / avoid / source tabs are rendered as compact tags instead of
        # stacked full-width rows so the user can scan them quickly.
        return self._tag_grid(values, columns=3)

    def _object_groups(self) -> QWidget:
        ctx = self.scene.context
        widget = QWidget()
        layout = QGridLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(7)
        groups = (
            ("Chủ thể", ctx.subject),
            ("Hành động", ctx.action),
            ("Địa điểm", ctx.location),
            ("Vật thể", ctx.objects),
            ("Bối cảnh / tâm trạng", ctx.mood),
        )
        for row, (title, values) in enumerate(groups):
            title_label = QLabel(title)
            title_label.setStyleSheet("font-weight:700; color:#a9bdd0;")
            tags = self._tag_grid(values, columns=3)
            layout.addWidget(title_label, row, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(tags, row, 1)
        layout.setColumnStretch(1, 1)
        return widget

    def _replace_analysis_tab(self, index: int, widget: QWidget, title: str):
        old = self.analysis_tabs.widget(index)
        self.analysis_tabs.removeTab(index)
        old.deleteLater()
        self.analysis_tabs.insertTab(index, widget, title)

    def _build_context_tabs(self):
        ctx = self.scene.context
        self._replace_analysis_tab(2, self._chips(ctx.keywords), "Từ khóa")
        self._replace_analysis_tab(3, self._object_groups(), "Đối tượng")
        self._replace_analysis_tab(4, self._chips(ctx.avoid), "Điều cần tránh")
        self._replace_analysis_tab(5, self._chips(ctx.suggested_sources), "Gợi ý nguồn")

    def set_scene(self, scene: SceneRecord):
        self.scene = scene
        self.title_label.setText(
            f"Xem, phân tích & đánh giá cảnh (Scene {scene.order:02d} / 24)"
        )
        self.scene_combo.clear()
        self.scene_combo.addItem(f"{scene.order:02d} / 24")
        self.en.setPlainText(scene.english_text)
        self.vi.setPlainText(scene.vietnamese_text or "Chưa có bản dịch tiếng Việt.")
        self._build_context_tabs()
        self.candidate = None
        self.video.clear_preview("PREVIEW VIDEO\nClick một kết quả ở khung 4")
        self.candidate_title.setText("Chưa chọn candidate")
        self.candidate_meta.setText("Nguồn · thời lượng · quyền sử dụng · điểm phù hợp")
        self.choose.setEnabled(False)
        self.waitlist.setEnabled(False)
        self.reject.setEnabled(False)
        self.compare.setEnabled(False)
        self.compare.setText("A/B")

    def set_candidate(self, candidate: CandidateRecord):
        self.candidate = candidate
        self.setToolTip(f"{candidate.creator}\n{candidate.source_url}")
        self.video.set_preview_pixmap(make_thumb(candidate.title, 1280, 720))
        self.candidate_title.setText(candidate.title)
        self.candidate_meta.setText(
            f"{candidate.provider.title()} · {_duration_text(candidate.duration)} · {candidate.rights_status} · "
            f"{candidate.resolution} · Điểm {candidate.score:.2f}"
        )
        self.choose.setEnabled(True)
        self.waitlist.setEnabled(True)
        self.reject.setEnabled(True)
        self.compare.setEnabled(True)

    def set_comparison_pending(self, pending: bool):
        self.compare.setText("A/B: chọn B" if pending else "A/B")


class SelectedPanel(Panel):
    CARD_WIDTH = 170
    CARD_HEIGHT = 102
    CARD_SPACING = 8

    def __init__(self, total_scenes: int = 0, scenes: list[SceneRecord] | None = None):
        self.total_scenes = total_scenes
        self._selection = SceneSelectionIndex.from_scenes(scenes or [])
        super().__init__(6, f"Danh sách cảnh đã chọn (0/{total_scenes})")

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFixedHeight(122)

        self.container = QWidget()
        self.container.setFixedHeight(self.CARD_HEIGHT + 8)
        self.row = QHBoxLayout(self.container)
        self.row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.row.setContentsMargins(2, 2, 2, 2)
        self.row.setSpacing(self.CARD_SPACING)
        self.scroll.setWidget(self.container)
        self.body.addWidget(self.scroll, 1)

    def _refresh_title(self):
        self.title_label.setText(
            f"Danh sách cảnh đã chọn ({len(self._selection)}/{self.total_scenes})"
        )

    def reset(self, total_scenes: int, scenes: list[SceneRecord] | None = None):
        self.total_scenes = total_scenes
        self._selection = SceneSelectionIndex.from_scenes(scenes or [])
        self._rebuild_cards()

    def set_scenes(self, scenes: list[SceneRecord]):
        self.total_scenes = len(scenes)
        self._selection.update_scenes(scenes)
        self._rebuild_cards()

    def add_or_replace_candidate(self, candidate: CandidateRecord | None):
        if candidate is None:
            return
        self._selection.add_or_replace(candidate)
        self._rebuild_cards()

    def set_final_clips(self, clips, scenes):
        # CandidateRecord is a presentation projection only; F014 owns final truth.
        self.reset(len(scenes), scenes)
        for clip in clips:
            self._selection.add_or_replace(CandidateRecord(
                clip.clip_id, clip.scene_id, clip.provider, clip.source_id, clip.title,
                clip.duration, clip.final_score, clip.rights_status,
                proposed_start=clip.start, proposed_end=clip.end))
        self._rebuild_cards()

    def ordered_scene_ids(self) -> list[str]:
        return self._selection.ordered_scene_ids()

    def selected_candidate(self, scene_id: str) -> CandidateRecord | None:
        return self._selection.get(scene_id)

    def _clear_layout(self):
        while self.row.count():
            item = self.row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _rebuild_cards(self):
        self._clear_layout()
        ordered = self._selection.ordered_candidates()
        for candidate in ordered:
            self.row.addWidget(self._make_card(candidate))

        count = len(ordered)
        content_width = max(1, count * self.CARD_WIDTH + max(0, count - 1) * self.CARD_SPACING + 8)
        self.container.setFixedWidth(content_width)
        self.container.setFixedHeight(self.CARD_HEIGHT + 8)
        self._refresh_title()

    def _make_card(self, candidate: CandidateRecord) -> QFrame:
        card = QFrame()
        card.setFixedSize(self.CARD_WIDTH, self.CARD_HEIGHT)
        card.setStyleSheet("background:#0b1a29; border:1px solid #24425f; border-radius:7px;")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        header = QHBoxLayout()
        scene_order = self._selection.scene_order.get(candidate.scene_id)
        if scene_order is None:
            try:
                scene_order = int(candidate.scene_id.rsplit("_", 1)[-1])
            except (TypeError, ValueError):
                scene_order = 0
        scene_label = QLabel(f"Cảnh {scene_order:02d}")
        scene_label.setStyleSheet("font-weight:800; color:#71b8ff;")
        header.addWidget(scene_label)
        header.addStretch(1)
        header.addWidget(QLabel(candidate.provider.title()))
        lay.addLayout(header)

        thumb = QLabel()
        thumb.setPixmap(make_thumb(candidate.title, self.CARD_WIDTH - 12, 46))
        thumb.setScaledContents(True)
        thumb.setFixedHeight(46)
        lay.addWidget(thumb)

        title = QLabel(candidate.title)
        title.setWordWrap(False)
        title.setToolTip(candidate.title)
        title.setFixedHeight(20)
        lay.addWidget(title)
        return card


class ExportPanel(Panel):
    def __init__(self, project_panel: ProjectPanel):
        super().__init__(7, "Xuất footage")
        self.project_panel = project_panel
        self.body.setSpacing(5)
        self.body.setContentsMargins(10, 7, 10, 7)

        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(10)

        destination = QVBoxLayout()
        destination.setSpacing(5)
        line = QHBoxLayout()
        line.setSpacing(5)
        self.dest = QLineEdit(project_panel.output_dir.text())
        self.dest.setMaximumWidth(270)
        self.dest.setToolTip(project_panel.output_dir.text())
        self.dest.textChanged.connect(self.dest.setToolTip)
        choose = QPushButton("Chọn...")
        choose.setFixedWidth(72)
        choose.clicked.connect(self._choose)
        line.addWidget(self.dest)
        line.addWidget(choose)
        line.addStretch(1)
        destination.addLayout(line)
        destination.addStretch(1)
        content.addLayout(destination, 48)

        options = QGridLayout()
        options.setContentsMargins(0, 0, 0, 0)
        options.setHorizontalSpacing(8)
        options.setVerticalSpacing(2)
        option_specs = (
            ("Cắt theo timestamp", "Cắt video theo timestamp đã chọn"),
            ("Đổi tên theo Scene ID", "Đổi tên file theo Scene ID"),
            ("Tạo manifest JSON", "Tạo footage_manifest.json"),
            ("Tạo index CSV", "Tạo footage_index.csv"),
            ("Lưu metadata & điểm", "Lưu metadata nguồn & điểm số"),
        )
        self.export_options = []
        for index, (label, tooltip) in enumerate(option_specs):
            cb = QCheckBox(label)
            cb.setToolTip(tooltip)
            cb.setChecked(True)
            self.export_options.append(cb)
            options.addWidget(cb, index // 2, index % 2)
        for index in (0, 2):
            self.export_options[index].setEnabled(False)
        self.export_options[0].setToolTip("Xuất thư viện luôn cắt theo timestamp đã duyệt")
        self.export_options[2].setToolTip("Manifest JSON bắt buộc để xác nhận thư viện hoàn chỉnh")
        self.export_options[4].setToolTip("Lưu provenance mở rộng; ID, điểm và quyền luôn có trong manifest")
        self.adapter_option = QCheckBox("Tạo gói AI_Video_Editor")
        options.addWidget(self.adapter_option, 2, 1)
        content.addLayout(options, 52)
        self.body.addLayout(content, 1)

        self.export = QPushButton("⇩  Xuất footage đã chọn")
        self.export.setObjectName("success")
        self.export.setFixedHeight(32)
        export_row = QHBoxLayout()
        export_row.addWidget(self.export, 1)
        self.cancel_export = QPushButton("Hủy")
        self.cancel_export.setEnabled(False)
        export_row.addWidget(self.cancel_export)
        self.body.addLayout(export_row)
        self.export_status = QLabel("")
        self.body.addWidget(self.export_status)

    def _choose(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục xuất footage")
        if folder:
            self.dest.setText(folder)

