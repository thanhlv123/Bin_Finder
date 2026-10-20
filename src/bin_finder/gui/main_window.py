from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from bin_finder.demo_data import demo_scenes
from bin_finder.gui.panels import (
    CandidateCard,
    ExportPanel,
    ProjectPanel,
    ReviewPanel,
    SceneListPanel,
    SearchResultsPanel,
    SelectedPanel,
    SourcePanel,
)
from bin_finder.gui.search_worker import SearchWorker
from bin_finder.gui.acquisition_worker import AcquisitionWorker
from bin_finder.gui.workflow_worker import WorkflowWorker
from bin_finder.gui.final_review_worker import FinalReviewWorker
from bin_finder.final_selection import build_final_project
from bin_finder.final_export import ExportOptions
from bin_finder.gui.final_export_worker import FinalExportWorker
from bin_finder.acceptance import evaluate_project
from bin_finder.workflow import WorkflowRequest, WorkflowService
from bin_finder.acquisition import AcquisitionRequest, AcquisitionService
from bin_finder.gui.theme import APP_STYLE
from bin_finder.evaluation import ABComparison, ReviewDecision, ReviewStore
from bin_finder.models import CandidateRecord, SceneRecord
from bin_finder.provider_config import ProviderConfig
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.service import DiscoveryService, SearchBatchResult, SearchOptions


_PROVIDER_LABELS = {
    "YouTube": "youtube",
    "Storyblocks": "storyblocks",
    "Pexels": "pexels",
    "Pixabay": "pixabay",
    "Báo điện tử": "news",
    "Thư viện local": "local",
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bin Finder")
        self.resize(1640, 980)
        self.setMinimumSize(1500, 820)
        self.setStyleSheet(APP_STYLE)

        self.scenes = demo_scenes()
        self._current_scene = self.scenes[0]
        self._search_workers: set[SearchWorker] = set()
        self._ab_anchor: CandidateRecord | None = None
        self._acquisition_worker = None
        self.acquired_assets = {}
        self._workflow_worker = None
        self.workflow_results = {}
        self.final_selections = ()
        self._final_worker = None
        self._export_worker = None
        self._final_item = None
        self._final_options = ()
        self._final_generation = 0

        project_root = Path(__file__).resolve().parents[3]
        self.provider_config = ProviderConfig.load(project_root)
        self.provider_registry = ProviderRegistry.from_config(self.provider_config)
        self.discovery_service = DiscoveryService(self.provider_registry)

        self._build()
        self._search_scene(self._current_scene)

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(6)
        outer.addWidget(self._header())
        outer.addWidget(self._top_navigation())

        # F002 deliberately preserves the accepted F001.5 fixed layout.
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
        self.review_panel.choose.setText("Chọn candidate")
        self.review_panel.choose.setToolTip("Duyệt candidate để tải/phân tích; chưa duyệt clip cuối")
        self.acquire_button = QPushButton("Tải footage đã duyệt")
        self.cancel_acquire_button = QPushButton("Hủy tải")
        self.cancel_acquire_button.setEnabled(False)
        self.acquisition_status = QLabel("")
        acquisition_actions = QHBoxLayout()
        acquisition_actions.addWidget(self.acquire_button)
        acquisition_actions.addWidget(self.cancel_acquire_button)
        acquisition_actions.addWidget(self.acquisition_status)
        self.review_panel.body.addLayout(acquisition_actions)
        self.acquire_button.clicked.connect(self._acquire_current_candidate)
        self.cancel_acquire_button.clicked.connect(self._cancel_acquisition)
        self.workflow_button = QPushButton("Tải và phân tích tư liệu đã duyệt")
        self.cancel_workflow_button = QPushButton("Hủy xử lý")
        self.cancel_workflow_button.setEnabled(False)
        self.workflow_status = QLabel("")
        workflow_actions = QHBoxLayout()
        workflow_actions.addWidget(self.workflow_button)
        workflow_actions.addWidget(self.cancel_workflow_button)
        workflow_actions.addWidget(self.workflow_status)
        self.review_panel.body.addLayout(workflow_actions)
        self.workflow_button.clicked.connect(self._process_current_candidate)
        self.cancel_workflow_button.clicked.connect(self._cancel_workflow)
        self.prepare_final_button = QPushButton("Chuẩn bị clip cuối")
        self.final_button = QPushButton("Duyệt clip cuối")
        self.final_button.setEnabled(False)
        self.final_options_combo = QComboBox()
        final_actions = QHBoxLayout()
        final_actions.addWidget(self.prepare_final_button)
        final_actions.addWidget(self.final_options_combo, 1)
        final_actions.addWidget(self.final_button)
        self.review_panel.body.addLayout(final_actions)
        self.prepare_final_button.clicked.connect(self._prepare_final)
        self.final_button.clicked.connect(self._approve_final)
        self.export_panel = ExportPanel(self.project_panel)
        self.export_panel.export.clicked.connect(self._export_final)
        self.export_panel.cancel_export.clicked.connect(self._cancel_export)
        self.export_panel.dest.textChanged.connect(self._refresh_acceptance)
        self.project_panel.project_name.textChanged.connect(self._project_changed)
        self._refresh_acceptance()
        right.setFixedWidth(650)
        self.export_panel.setFixedHeight(168)
        right_layout.addWidget(self.review_panel, 1)
        right_layout.addWidget(self.export_panel, 0)

        content_layout.addWidget(left, 1)
        content_layout.addWidget(right, 0)
        outer.addWidget(content, 1)

        self.scene_panel.scene_changed.connect(self._scene_changed)
        self.search_panel.candidate_changed.connect(self.review_panel.set_candidate)
        self.search_panel.candidate_changed.connect(self._clear_final_options)
        self.review_panel.select_candidate.connect(self._candidate_selected)
        self.review_panel.waitlist_candidate.connect(self._candidate_waitlisted)
        self.review_panel.reject_candidate.connect(self._candidate_rejected)
        self.review_panel.compare_candidate.connect(self._candidate_compared)
        self.project_panel.output_dir.textChanged.connect(self.export_panel.dest.setText)
        self.project_panel.split_requested.connect(self._prototype_split)

        for button in self.search_panel.findChildren(QPushButton):
            if "Tìm kiếm lại" in button.text():
                button.clicked.connect(self._search_current_scene)
        for button in self.source_panel.findChildren(QPushButton):
            if "Dùng AI tạo nhiều query" in button.text():
                button.setCheckable(True)
                button.setChecked(True)

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
        self._current_scene = scene
        self._clear_final_options()
        self.review_panel.set_scene(scene)
        self._search_scene(scene)

    def _search_current_scene(self):
        self._search_scene(self._current_scene)

    def _source_options(self) -> SearchOptions:
        checks = {box.text(): box for box in self.source_panel.findChildren(QCheckBox)}
        provider_keys = tuple(
            key
            for label, key in _PROVIDER_LABELS.items()
            if label in checks and checks[label].isChecked()
        )

        combos = self.source_panel.findChildren(QComboBox)
        duration_text = "Tất cả"
        resolution_text = "Tất cả (>=720p)"
        orientation_text = "Tất cả"
        for combo in combos:
            if combo.findText("< 4 phút") >= 0:
                duration_text = combo.currentText()
            elif combo.findText("1080p+") >= 0:
                resolution_text = combo.currentText()
            elif combo.findText("16:9") >= 0:
                orientation_text = combo.currentText()

        duration_bucket = {
            "< 4 phút": "short",
            "4–20 phút": "medium",
            "> 20 phút": "long",
        }.get(duration_text, "any")
        min_height = {"1080p+": 1080, "4K": 2160}.get(resolution_text, 720)
        orientation = {"16:9": "landscape", "9:16": "portrait", "1:1": "square"}.get(
            orientation_text, "any"
        )

        spins = self.source_panel.findChildren(QSpinBox)
        limit = spins[0].value() if spins else 20
        creative_commons = bool(
            checks.get("Creative Commons") and checks["Creative Commons"].isChecked()
        )
        multiple_queries = any(
            button.isCheckable()
            and button.isChecked()
            and "Dùng AI tạo nhiều query" in button.text()
            for button in self.source_panel.findChildren(QPushButton)
        )
        return SearchOptions(
            provider_keys=provider_keys,
            limit=limit,
            orientation=orientation,
            min_height=min_height,
            duration_bucket=duration_bucket,
            creative_commons_only=creative_commons,
            multiple_queries=multiple_queries,
        )

    def _clear_search_grid(self):
        while self.search_panel.grid.count():
            item = self.search_panel.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _set_search_loading(self, scene: SceneRecord):
        self.search_panel._scene_id = scene.scene_id
        self._clear_search_grid()
        self.search_panel.title_label.setText(
            f"Kết quả tìm kiếm cho cảnh {scene.order:02d} (đang tìm...)"
        )
        loading = QLabel("Đang tìm kiếm trên các nguồn đã chọn...")
        loading.setObjectName("muted")
        loading.setWordWrap(True)
        self.search_panel.grid.addWidget(loading, 0, 0, 1, 3)
        self.search_panel.scroll.verticalScrollBar().setValue(0)

    def _search_scene(self, scene: SceneRecord):
        self._set_search_loading(scene)
        worker = SearchWorker(self.discovery_service, scene, self._source_options())
        self._search_workers.add(worker)
        worker.result_ready.connect(self._search_complete)
        worker.failed.connect(self._search_failed)
        worker.finished.connect(lambda worker=worker: self._release_worker(worker))
        worker.start()

    def _release_worker(self, worker: SearchWorker):
        self._search_workers.discard(worker)
        worker.deleteLater()

    def _search_complete(self, result: SearchBatchResult):
        if result.scene_id != self._current_scene.scene_id:
            return
        self._clear_search_grid()
        scene = self._current_scene
        self.search_panel.title_label.setText(
            f"Kết quả tìm kiếm cho cảnh {scene.order:02d} ({len(result.candidates)} kết quả)"
        )
        tooltip_parts = []
        if result.query_texts:
            tooltip_parts.append("Query: " + " | ".join(result.query_texts))
        if result.notices:
            tooltip_parts.append("Thông báo: " + " | ".join(dict.fromkeys(result.notices)))
        self.search_panel.setToolTip("\n".join(tooltip_parts))

        if not result.candidates:
            message = "Không có kết quả."
            if result.notices:
                message += "\n" + "\n".join(dict.fromkeys(result.notices))
            empty = QLabel(message)
            empty.setObjectName("muted")
            empty.setWordWrap(True)
            self.search_panel.grid.addWidget(empty, 0, 0, 1, 3)
        else:
            for index, candidate in enumerate(result.candidates):
                card = CandidateCard(candidate)
                card.clicked.connect(self.search_panel.candidate_changed.emit)
                self.search_panel.grid.addWidget(card, index // 3, index % 3)

        self.search_panel.scroll.verticalScrollBar().setValue(0)

    def _search_failed(self, scene_id: str, message: str):
        if scene_id != self._current_scene.scene_id:
            return
        self._clear_search_grid()
        self.search_panel.title_label.setText("Kết quả tìm kiếm (lỗi)")
        label = QLabel(message)
        label.setObjectName("muted")
        label.setWordWrap(True)
        self.search_panel.grid.addWidget(label, 0, 0, 1, 3)

    def _review_store(self) -> ReviewStore:
        return ReviewStore.for_project(self.project_panel.project_name.text())

    def _acquire_current_candidate(self):
        candidate = self.review_panel.candidate
        if candidate is None or self._acquisition_worker is not None or self._workflow_worker is not None:
            return
        review = next((item for item in self._review_store().decisions()
                       if item.scene_id == candidate.scene_id
                       and item.candidate_id == candidate.candidate_id), None)
        if review is None or review.decision != "accepted":
            self.acquisition_status.setText("Cần duyệt chọn trước khi tải.")
            return
        if candidate.provider not in {"pexels", "pixabay"}:
            self.acquisition_status.setText("Nguồn chưa hỗ trợ tải.")
            return
        worker = AcquisitionWorker(AcquisitionService(), AcquisitionRequest(candidate, review, True))
        self._acquisition_worker = worker
        self.acquire_button.setEnabled(False)
        self.cancel_acquire_button.setEnabled(True)
        self.acquisition_status.setText("Đang tải…")
        worker.progress.connect(self._acquisition_progress)
        worker.result_ready.connect(self._acquisition_complete)
        worker.failed.connect(self.acquisition_status.setText)
        worker.cancelled.connect(self._acquisition_cancelled)
        worker.finished.connect(self._acquisition_finished)
        worker.start()

    def _cancel_acquisition(self):
        if self._acquisition_worker is not None:
            self._acquisition_worker.requestInterruption()

    def _acquisition_progress(self, done, total):
        self.acquisition_status.setText(
            f"Đang tải {min(100, max(0, int(done * 100 / total)))}%" if total else "Đang tải…")

    def _acquisition_complete(self, result):
        self._clear_final_options()
        # Retain the reference for explicit local analysis; do not create a clip
        # or alter human review, scene selection, verification or export state.
        self.acquired_assets[result.candidate.candidate_id] = result
        if self.review_panel.candidate == self._acquisition_worker.request.candidate:
            self.review_panel.set_candidate(result.candidate)
        self.acquisition_status.setText("Đã có trong cache" if result.cache_hit else "Đã tải")

    def _acquisition_cancelled(self):
        self.acquisition_status.setText("Đã hủy")

    def _acquisition_finished(self):
        worker = self._acquisition_worker
        self._acquisition_worker = None
        self.acquire_button.setEnabled(True)
        self.cancel_acquire_button.setEnabled(False)
        worker.deleteLater()

    def _process_current_candidate(self):
        candidate = self.review_panel.candidate
        if candidate is None or self._workflow_worker is not None or self._acquisition_worker is not None:
            return
        self._clear_final_options()
        request = WorkflowRequest(tuple(self.scenes), (candidate,),
                                  self._review_store().decisions(), True)
        worker = WorkflowWorker(WorkflowService(
            project_id=self.project_panel.project_name.text()), request)
        self._workflow_worker = worker
        self.workflow_button.setEnabled(False)
        self.acquire_button.setEnabled(False)
        self.cancel_workflow_button.setEnabled(True)
        worker.progress.connect(self._workflow_progress)
        worker.result_ready.connect(self._workflow_complete)
        worker.failed.connect(self.workflow_status.setText)
        worker.cancelled.connect(self._workflow_cancelled)
        worker.finished.connect(self._workflow_finished)
        worker.start()

    def _cancel_workflow(self):
        if self._workflow_worker is not None:
            self._workflow_worker.requestInterruption()

    def _workflow_progress(self, event):
        labels = {"acquiring": "Đang tải…", "analyzing": "Đang phân tích…",
                  "analyzed": "Đã phân tích", "failed": "Thất bại",
                  "cancelled": "Đã hủy", "skipped": "Cần cho phép tải"}
        text = labels.get(event.stage, "Đang xử lý…")
        if event.percent is not None:
            text += f" {event.percent}%"
        self.workflow_status.setText(text)

    def _workflow_complete(self, result):
        self._clear_final_options()
        for item in result.items:
            key = (item.candidate.scene_id, item.candidate.candidate_id,
                   item.candidate.provider, item.candidate.source_id)
            self.workflow_results[key] = item
            current = self.review_panel.candidate
            if current is not None and key == (current.scene_id, current.candidate_id,
                                               current.provider, current.source_id):
                self.review_panel.set_candidate(item.candidate)
        failed = next((item for item in result.items if item.stage != "analyzed"), None)
        self.workflow_status.setText(
            f"Chưa hoàn tất: {failed.message}" if failed else "Hoàn tất; cần kiểm tra và duyệt cuối")

    def _workflow_cancelled(self):
        self.workflow_status.setText("Đã hủy")

    def _workflow_finished(self):
        worker = self._workflow_worker
        self._workflow_worker = None
        self.workflow_button.setEnabled(True)
        self.acquire_button.setEnabled(True)
        self.cancel_workflow_button.setEnabled(False)
        worker.deleteLater()

    def closeEvent(self, event):
        if self._export_worker is not None:
            self._cancel_export()
            event.ignore()
            return
        if self._final_worker is not None:
            event.ignore()
            return
        if self._workflow_worker is not None:
            self._cancel_workflow()
            self.workflow_status.setText("Đang hủy; đóng lại khi hoàn tất.")
            event.ignore()
            return
        if self._acquisition_worker is not None:
            self._cancel_acquisition()
            self.acquisition_status.setText("Đang hủy; đóng lại khi hoàn tất.")
            event.ignore()
            return
        if any(worker.isRunning() for worker in self._search_workers):
            event.ignore()
            return
        super().closeEvent(event)

    def _record_review(self, candidate: CandidateRecord, decision: str):
        self._review_store().record_decision(
            ReviewDecision(
                scene_id=candidate.scene_id,
                candidate_id=candidate.candidate_id,
                decision=decision,
                provider=candidate.provider,
                source_id=candidate.source_id,
                title=candidate.title,
                score=candidate.score,
                source_url=candidate.source_url, creator=candidate.creator,
                rights_status=candidate.rights_status, source_metadata=candidate.source_metadata,
            )
        )

    def _candidate_selected(self, candidate: CandidateRecord | None):
        if candidate is None:
            return
        self._record_review(candidate, "accepted")
        self.workflow_status.setText("Đã duyệt candidate; cần duyệt clip cuối")

    def _candidate_waitlisted(self, candidate: CandidateRecord | None):
        if candidate is None:
            return
        self._record_review(candidate, "waitlist")

    def _candidate_rejected(self, candidate: CandidateRecord | None):
        if candidate is None:
            return
        self._record_review(candidate, "rejected")

    def _candidate_compared(self, candidate: CandidateRecord | None):
        if candidate is None:
            return
        anchor = self._ab_anchor
        if (
            anchor is None
            or anchor.scene_id != candidate.scene_id
            or anchor.candidate_id == candidate.candidate_id
        ):
            self._ab_anchor = candidate
            self.review_panel.set_comparison_pending(True)
            return

        box = QMessageBox(self)
        box.setWindowTitle("So sánh A/B")
        box.setText(
            "Chọn footage phù hợp hơn cho cảnh này.\n\n"
            f"A: {anchor.title}\n"
            f"B: {candidate.title}"
        )
        button_a = box.addButton("Chọn A", QMessageBox.ButtonRole.AcceptRole)
        button_b = box.addButton("Chọn B", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Hủy", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is button_a:
            winner = anchor
        elif clicked is button_b:
            winner = candidate
        else:
            winner = None

        if winner is not None:
            self._review_store().add_comparison(
                ABComparison(
                    scene_id=candidate.scene_id,
                    candidate_a_id=anchor.candidate_id,
                    candidate_b_id=candidate.candidate_id,
                    winner_id=winner.candidate_id,
                )
            )

        self._ab_anchor = None
        self.review_panel.set_comparison_pending(False)

    def _prototype_split(self, text: str):
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
        self.final_selections = ()
        self.workflow_results.clear()
        self._clear_final_options()
        self._refresh_acceptance()
        self._current_scene = scenes[0]
        self.scene_panel.set_scenes(scenes)
        self.selected_panel.reset(total_scenes=len(scenes), scenes=scenes)
        self.review_panel.set_scene(scenes[0])
        self._ab_anchor = None
        self.review_panel.set_comparison_pending(False)
        self._search_scene(scenes[0])

    def _project_changed(self):
        self.final_selections = ()
        self.workflow_results.clear()
        self._clear_final_options()
        self.selected_panel.reset(len(self.scenes), self.scenes)
        self.scene_panel.set_scenes(self.scenes)
        self._refresh_acceptance()

    def _clear_final_options(self, *_):
        self._final_generation += 1
        self._final_item = None
        self._final_options = ()
        self.final_options_combo.clear()
        self.final_button.setEnabled(False)

    def _final_context(self):
        return (self.project_panel.project_name.text(), tuple(self.scenes), self.final_selections, self._final_generation)

    def _start_final_worker(self, item, clip_id=None):
        if self._final_worker is not None:
            return
        scene = next((s for s in self.scenes if s.scene_id == item.candidate.scene_id), None)
        if scene is None:
            return
        worker = FinalReviewWorker(scene, item, self.scenes, self.final_selections, clip_id)
        self._final_worker = worker
        self._final_worker_context = self._final_context()
        self.final_button.setEnabled(False)
        self.prepare_final_button.setEnabled(False)
        worker.result_ready.connect(self._final_complete)
        worker.failed.connect(self.workflow_status.setText)
        worker.finished.connect(self._final_finished)
        worker.start()

    def _prepare_final(self):
        current = self.review_panel.candidate
        if current is None:
            return
        key = (current.scene_id, current.candidate_id, current.provider, current.source_id)
        item = self.workflow_results.get(key)
        self._clear_final_options()
        if item is None:
            self.workflow_status.setText("Clip chưa sẵn sàng")
            return
        self._start_final_worker(item)

    def _approve_final(self):
        index = self.final_options_combo.currentIndex()
        if self._final_item is not None and 0 <= index < len(self._final_options):
            self._start_final_worker(self._final_item, self._final_options[index].clip_id)

    def _final_complete(self, result):
        worker = self._final_worker
        if self._final_worker_context != self._final_context():
            return
        if worker.clip_id is None:
            current = self.review_panel.candidate
            if current is None or (current.scene_id, current.candidate_id, current.provider, current.source_id) != (
                    worker.item.candidate.scene_id, worker.item.candidate.candidate_id,
                    worker.item.candidate.provider, worker.item.candidate.source_id):
                return
            self._final_item, self._final_options = result
            self.final_options_combo.clear()
            for option in self._final_options:
                p = option.proposal
                self.final_options_combo.addItem(f"{p.start:.2f}–{p.end:.2f}s | {option.final_score:.2f}")
            self.workflow_status.setText("Cần duyệt clip cuối" if self._final_options else "Clip chưa sẵn sàng")
        elif result.accepted:
            self.final_selections = result.selections
            self.selected_panel.set_final_clips(self.final_selections, self.scenes)
            self.scene_panel.mark_selected(worker.scene.scene_id)
            self.workflow_status.setText("Đã duyệt clip cuối")
            self._refresh_acceptance()
        else:
            self.workflow_status.setText("Không thể duyệt: " + result.reason)

    def _final_finished(self):
        worker = self._final_worker
        self._final_worker = None
        self.prepare_final_button.setEnabled(True)
        self.final_button.setEnabled(bool(self._final_options))
        worker.deleteLater()

    def _refresh_acceptance(self, *_):
        project = build_final_project(self.project_panel.project_name.text(), self.scenes,
                                      self.final_selections, self.export_panel.dest.text())
        self.acceptance_report = evaluate_project(project)
        r = self.acceptance_report
        reasons = []
        if r.unresolved_scene_ids:
            reasons.append("Chưa đủ cảnh")
        if r.low_score_scene_ids:
            reasons.append("Điểm cuối thấp")
        if r.source_rotation_issues:
            reasons.append("Xung đột nguồn")
        if r.overlap_issues:
            reasons.append("Trùng khoảng thời gian")
        if r.duration_issue:
            reasons.append(r.duration_issue)
        self.export_panel.export.setEnabled(r.ready and self._export_worker is None)
        self.export_panel.export.setToolTip("Sẵn sàng xuất" if r.ready else "; ".join(reasons))
        self.export_panel.title_label.setText("Xuất footage · " + ("Sẵn sàng xuất" if r.ready else "; ".join(reasons)))

    def _export_final(self):
        self._refresh_acceptance()
        if not self.acceptance_report.ready or self._export_worker is not None:
            return
        checks = self.export_panel.export_options
        options = ExportOptions(csv_index=checks[3].isChecked(),
            integration_adapter=self.export_panel.adapter_option.isChecked(),
            scene_id_filenames=checks[1].isChecked(), include_metadata=checks[4].isChecked())
        worker = FinalExportWorker(self.project_panel.project_name.text(), self.scenes,
            self.final_selections, self.export_panel.dest.text(), options)
        self._export_worker = worker
        worker.progress.connect(self._export_progress)
        worker.result_ready.connect(self._export_complete)
        worker.failed.connect(self.export_panel.export_status.setText)
        worker.finished.connect(self._export_finished)
        self.export_panel.export.setEnabled(False)
        self.export_panel.cancel_export.setEnabled(True)
        self.export_panel.export_status.setText("Đang xuất footage…")
        worker.start()

    def _cancel_export(self):
        if self._export_worker is not None:
            self._export_worker.requestInterruption()
            self.export_panel.export_status.setText("Đang hủy; chờ lần cắt hiện tại hoàn tất")

    def _export_progress(self, progress):
        self.export_panel.export_status.setText(
            f"{progress.completed}/{progress.total} · {progress.scene_id}")

    def _export_complete(self, result):
        messages = {"success": "Đã xuất footage", "cancelled": "Đã hủy xuất footage",
                    "failed": "Xuất thất bại: " + result.error, "not_ready": "Chưa READY"}
        self.export_panel.export_status.setText(messages[result.status])

    def _export_finished(self):
        worker = self._export_worker
        self._export_worker = None
        self.export_panel.cancel_export.setEnabled(False)
        self._refresh_acceptance()
        worker.deleteLater()
