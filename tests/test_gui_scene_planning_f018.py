"""F018 GUI: the existing split action runs the production planner and keeps lifecycle semantics."""
from PyQt6.QtWidgets import QApplication

from bin_finder.clips.models import ClipPolicy
from bin_finder.demo_data import demo_scenes
from bin_finder.gui.main_window import MainWindow
from bin_finder.search.query_builder import build_scene_queries

APP = QApplication.instance() or QApplication([])
SCRIPT = ("At ten o'clock at night, office lights in Lujiazui are still burning. "
          "Young workers remain at their desks long after dinner.\n\n"
          "The next morning the streets fill with commuters heading toward the metro station.")


def window_with_search_log(monkeypatch):
    searched = []
    monkeypatch.setattr(MainWindow, "_search_scene", lambda self, scene: searched.append(scene))
    window = MainWindow()
    searched.clear()  # startup already searched the demo scene
    return window, searched


def test_default_scenes_are_unchanged_demo_scenes(monkeypatch):
    window, _ = window_with_search_log(monkeypatch)
    try:
        assert window.scenes == demo_scenes()
    finally:
        window.close()


def test_split_uses_planner_updates_ui_and_searches_new_scene(monkeypatch):
    window, searched = window_with_search_log(monkeypatch)
    try:
        window.project_panel.split_requested.emit(SCRIPT)
        APP.processEvents()
        assert [s.scene_id for s in window.scenes] == ["scene_001", "scene_002", "scene_003"]
        assert window._current_scene is window.scenes[0]
        # set_scenes and the explicit call both search (pre-existing); only the new scene is used.
        assert searched and all(item is window.scenes[0] for item in searched)
        assert window.scenes[0].context.location == ("Lujiazui",)
        assert all(build_scene_queries(s) for s in window.scenes)
        assert any(s.target_duration != 5.0 for s in window.scenes)
    finally:
        window.close()


def test_split_invalidates_old_selections_and_refreshes_readiness(monkeypatch):
    window, _ = window_with_search_log(monkeypatch)
    try:
        sentinel = object()
        window.final_selections = (sentinel,)
        window._final_item = sentinel
        generation = window._final_generation
        window.project_panel.split_requested.emit(SCRIPT)
        assert window.final_selections == ()
        assert window._final_item is None and window._final_generation > generation
        assert not window.workflow_results
        assert window.acceptance_report is not None and not window.acceptance_report.ready
    finally:
        window.close()


def test_empty_and_oversized_input_leave_state_untouched(monkeypatch):
    window, searched = window_with_search_log(monkeypatch)
    try:
        before = list(window.scenes)
        window.project_panel.split_requested.emit("  \n ")
        assert window.scenes == before and not searched
        window.project_panel.split_requested.emit("a" * 60_000)
        assert window.scenes == before and not searched
        assert "script-too-long" in window.workflow_status.text()
    finally:
        window.close()


def test_identical_script_replans_identically(monkeypatch):
    window, _ = window_with_search_log(monkeypatch)
    try:
        window.project_panel.split_requested.emit(SCRIPT)
        first = list(window.scenes)
        window.project_panel.split_requested.emit(SCRIPT)
        assert window.scenes == first
    finally:
        window.close()


def test_gui_split_of_long_narration_stays_within_clip_policy(monkeypatch):
    from test_scene_planning_f018 import LONG_NARRATION
    window, searched = window_with_search_log(monkeypatch)
    try:
        window.project_panel.split_requested.emit(LONG_NARRATION)
        assert len(window.scenes) >= 4
        assert all(ClipPolicy().min_duration <= s.target_duration <= ClipPolicy().max_duration
                   for s in window.scenes)
        assert all(s.context.keywords for s in window.scenes)
        assert searched and all(item is window.scenes[0] for item in searched)
    finally:
        window.close()
