"""ZB-03A PyQt6 offscreen UI smoke, no user files, no live footage."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFileDialog, QListWidget

from bin_finder.timeline_review_demo import build_demo
from bin_finder.timeline_review_gui import TimelineReviewWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def review_window(app):
    scenes, plan, draft = build_demo("travel")
    window = TimelineReviewWindow(scenes, plan, draft)
    yield window
    window.close()


def test_ui_lists_narration_and_shot_cards(review_window):
    window = review_window
    assert window.scene_list.count() == 4
    assert window.findChild(QListWidget, "zb03a_candidate_list") is not None
    assert window.active_shot_id == "s1"
    assert "s1" in window.active_title.text()
    assert len(window.draft.items) == 3
    assert window.draft.counts()["proposed"] == 2
    assert window.draft.counts()["needs_editorial_resolution"] == 1
    assert "Chờ duyệt" in window.info.text()


def test_changing_candidate_marks_reviewed_only_after_click(review_window):
    window = review_window
    current = window.draft.item("s1")
    assert current.reviewed is False
    assert window.candidate_list.count() >= 2
    window.candidate_list.setCurrentRow(1)
    QTest.mouseClick(window.choose_button, Qt.MouseButton.LeftButton)
    new_state = window.draft.item("s1")
    assert new_state.selected_candidate_id == current.candidates[1].candidate_id
    assert new_state.reviewed is False
    QTest.mouseClick(window.review_button, Qt.MouseButton.LeftButton)
    assert window.draft.item("s1").review_status == "reviewed"
    QTest.mouseClick(window.lock_button, Qt.MouseButton.LeftButton)
    assert window.draft.item("s1").locked is True
    assert not window.choose_button.isEnabled()
    assert not window.review_button.isEnabled()
    QTest.mouseClick(window.lock_button, Qt.MouseButton.LeftButton)
    assert window.draft.item("s1").locked is False


def test_select_nonsearch_shot_is_explicitly_unresolved(review_window):
    window = review_window
    window.select_shot("s2")
    assert window.active_shot_id == "s2"
    assert window.draft.item("s2").strategy == "transition"
    assert "Cần quyết định" in window.active_status.text()
    assert not window.choose_button.isEnabled()
    assert not window.review_button.isEnabled()
    assert not window.local_button.isEnabled()
    assert not window.lock_button.isEnabled()
    assert "THUMBNAIL MINH HỌA" in window.preview_text.text()


def test_narration_item_selects_corresponding_shot(review_window):
    window = review_window
    window.scene_list.setCurrentRow(3)
    assert window.active_shot_id == "s3"
    assert "s3" in window.active_title.text()


def test_reviewer_note_in_gui_is_session_only(review_window):
    window = review_window
    window.select_shot("s1")
    window.note.setPlainText("Góc quay đẹp nhưng cần so lại")
    QTest.mouseClick(window.save_note_button, Qt.MouseButton.LeftButton)
    assert window.draft.item("s1").note == "Góc quay đẹp nhưng cần so lại"
    window.select_shot("s3")
    assert window.note.toPlainText() == ""
    window.select_shot("s1")
    assert window.note.toPlainText() == "Góc quay đẹp nhưng cần so lại"


def test_explicit_file_picker_only_adds_unverified_reference(review_window, tmp_path, monkeypatch):
    path = tmp_path / "my synthetic clip.mp4"
    path.write_bytes(b"nothing playable here")
    window = review_window
    window.select_shot("s1")
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName",
        lambda *args, **kwargs: (str(path), "Video (*.mp4)"),
    )
    QTest.mouseClick(window.local_button, Qt.MouseButton.LeftButton)
    item = window.draft.item("s1")
    assert item.reviewed is False
    assert item.locked is False
    assert item.review_status == "proposed"
    chosen = next(c for c in item.candidates if c.candidate_id == item.selected_candidate_id)
    assert chosen.origin == "local"
    assert chosen.local_file == str(path.resolve())
    assert "CHƯA CÓ PREVIEW VIDEO THẬT" in window.preview_text.text()
