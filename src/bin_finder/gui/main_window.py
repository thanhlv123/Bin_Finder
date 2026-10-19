from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bin_finder.demo_data import demo_candidates, demo_scenes
from bin_finder.gui.panels import (
    ExportPanel,
    ProjectPanel,
    ReviewPanel,
    SceneListPanel,
    SearchResultsPanel,
    SelectedPanel,
    SourcePanel,
)
from bin_finder.gui.theme import APP_STYLE
from bin_finder.models import CandidateRecord, SceneRecord


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bin Finder")
        self.resize(1640, 980)
        self.setMinimumSize(1500, 820)
        self.setStyleSheet(APP_STYLE)
        self.scenes = demo_scenes()
        self._build()

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(6)
        outer.addWidget(self._header())
        outer.addWidget(self._top_navigation())

        # F001.5 removes user-draggable splitters. The approved workspace keeps
        # stable proportions while the main window itself may still be resized.
        # Left workspace: project/scene + search/results. Right workspace:
        # review + export, widened to make the video preview as useful as possible.
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(6)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)

        columns = QWidget()
        columns_layout = QHBoxLayout(columns)
        columns_layout.setContentsMargins(0, 0, 0, 0)
        columns_layout.setSpacing(6)

        project_scene_column = QWidget()
        project_scene_layout = QVBoxLayout(project_scene_column)
        project_scene_layout.setContentsMargins(0, 0, 0, 0)
        project_scene_layout.setSpacing(6)
        self.project_panel = ProjectPanel()
        self.scene_panel = SceneListPanel(self.scenes)
        project_scene_column.setFixedWidth(330)
        project_scene_layout.addWidget(self.project_panel, 46)
        project_scene_layout.addWidget(self.scene_panel, 54)

        search_column = QWidget()
        search_column_layout = QVBoxLayout(search_column)
        search_column_layout.setContentsMargins(0, 0, 0, 0)
        search_column_layout.setSpacing(6)
        self.source_panel = SourcePanel()
        self.source_panel.setFixedHeight(250)
        self.search_panel = SearchResultsPanel(self.scenes[0].scene_id)
        search_column_layout.addWidget(self.source_panel, 30)
        search_column_layout.addWidget(self.search_panel, 70)

        # Stable non-draggable proportions. Search/results keeps enough width for
        # exactly three result thumbnails per row.
        columns_layout.addWidget(project_scene_column, 34)
        columns_layout.addWidget(search_column, 66)
        left_layout.addWidget(columns, 1)

        self.selected_panel = SelectedPanel(total_scenes=len(self.scenes), scenes=self.scenes)
        self.selected_panel.setFixedHeight(168)
        left_layout.addWidget(self.selected_panel, 0)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        self.review_panel = ReviewPanel(self.scenes[0])
        self.export_panel = ExportPanel(self.project_panel)
        right.setFixedWidth(650)
        self.export_panel.setFixedHeight(168)
        right_layout.addWidget(self.review_panel, 1)
        right_layout.addWidget(self.export_panel, 0)

        # Widen the review column and lock the relationship between the two
        # workspaces. No splitter handle is exposed to the user.
        content_layout.addWidget(left, 1)
        content_layout.addWidget(right, 0)
        outer.addWidget(content, 1)

        self.scene_panel.scene_changed.connect(self._scene_changed)
        self.search_panel.candidate_changed.connect(self.review_panel.set_candidate)
        self.review_panel.select_candidate.connect(self._candidate_selected)
        self.project_panel.output_dir.textChanged.connect(self.export_panel.dest.setText)
        self.project_panel.split_requested.connect(self._prototype_split)

        self._seed_demo_selection()

    def _header(self):
        header = QFrame()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(4, 2, 4, 6)
        title_box = QVBoxLayout()
        title = QLabel("Bin Finder")
        title.setObjectName("appTitle")
        subtitle = QLabel("Tìm kiếm và cắt footage từ nhiều nguồn theo kịch bản")
        subtitle.setObjectName("subtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addStretch(1)
        project = QPushButton("▣  Dự án: CUBA_VIDEO_001")
        settings = QPushButton("⚙  Cài đặt")
        help_button = QPushButton("?  Hướng dẫn")
        layout.addWidget(project)
        layout.addWidget(settings)
        layout.addWidget(help_button)
        return header

    def _top_navigation(self):
        nav = QFrame()
        nav.setObjectName("topNavigation")
        layout = QHBoxLayout(nav)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.navigation_group = QButtonGroup(self)
        self.navigation_group.setExclusive(True)
        entries = (
            ("▣  Dự án && Kịch bản", "project"),
            ("⌕  Tìm kiếm footage", "search"),
            ("▶  Xem && chọn cảnh", "review"),
            ("✓  Quản lý cảnh đã chọn", "selected"),
        )
        for index, (label, role) in enumerate(entries):
            button = QPushButton(label)
            button.setObjectName("topNavButton")
            button.setProperty("navRole", role)
            button.setCheckable(True)
            button.setMinimumHeight(42)
            button.setChecked(index == 0)
            self.navigation_group.addButton(button, index)
            layout.addWidget(button, 1)
        return nav

    def _scene_changed(self, scene: SceneRecord):
        self.review_panel.set_scene(scene)
        self.search_panel.set_scene(scene.scene_id)

    def _candidate_selected(self, candidate: CandidateRecord | None):
        if candidate is None:
            return
        self.scene_panel.mark_selected(candidate.scene_id)
        self.selected_panel.add_or_replace_candidate(candidate)

    def _seed_demo_selection(self):
        selected_scenes = [scene for scene in self.scenes if scene.status == "selected"]
        if not selected_scenes:
            return
        for index, scene in enumerate(selected_scenes):
            candidates = demo_candidates(scene.scene_id)
            if not candidates:
                continue
            candidate = candidates[min(index, len(candidates) - 1)]
            self.selected_panel.add_or_replace_candidate(candidate)

    def _prototype_split(self, text: str):
        # F001 deliberately does not call any AI provider yet. This deterministic
        # preview keeps the GUI workflow usable while provider contracts are built.
        chunks = [part.strip() for part in text.replace("\n", " ").split(".") if part.strip()]
        if not chunks:
            return
        scenes = [
            SceneRecord(
                scene_id=f"scene_{index:03d}",
                order=index,
                english_text=chunk + ".",
                target_duration=5.0,
            )
            for index, chunk in enumerate(chunks, start=1)
        ]
        self.scenes = scenes
        self.scene_panel.set_scenes(scenes)
        self.selected_panel.reset(total_scenes=len(scenes), scenes=scenes)
        self.search_panel.set_scene(scenes[0].scene_id)
        self.review_panel.set_scene(scenes[0])
