from PyQt6.QtWidgets import QApplication

from bin_finder.demo_data import demo_candidates, demo_scenes
from bin_finder.gui.panels import ReviewPanel


def app():
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    return instance


def test_review_panel_has_compact_decision_controls():
    app()
    panel = ReviewPanel(demo_scenes()[0])
    assert panel.choose.text() == "✓ Chọn (~5s)"
    assert panel.waitlist.text() == "⏳ Chờ"
    assert panel.reject.text() == "✕ Loại"
    assert panel.compare.text() == "A/B"
    assert panel.choose.isEnabled() is False
    assert panel.waitlist.isEnabled() is False
    assert panel.reject.isEnabled() is False
    assert panel.compare.isEnabled() is False

    candidate = demo_candidates("scene_001")[0]
    panel.set_candidate(candidate)
    assert panel.choose.isEnabled() is True
    assert panel.waitlist.isEnabled() is True
    assert panel.reject.isEnabled() is True
    assert panel.compare.isEnabled() is True


def test_review_panel_ab_pending_label_does_not_change_geometry():
    app()
    panel = ReviewPanel(demo_scenes()[0])
    before = panel.video.height()
    panel.set_comparison_pending(True)
    assert panel.compare.text() == "A/B: chọn B"
    assert panel.video.height() == before == 280
    panel.set_comparison_pending(False)
    assert panel.compare.text() == "A/B"
