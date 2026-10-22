"""F016 GUI acceptance: remote cache proof and historical workflow hints."""
from bin_finder import session_workflow
from bin_finder.session_store import SessionStore
from test_gui_session_recovery_f016 import new_window, close_window
from test_session_recovery_f016 import sample
from test_session_remote_f016 import make_case
from test_session_workflow_refs_f016 import fixture_workflow


def test_gui_remote_f012_proof_controls_ready_after_restart(tmp_path, monkeypatch):
    payload, _media, manifest_path, _manifest = make_case(tmp_path, monkeypatch)
    payload["scenes"][0]["target_duration"] = 60.0
    root = tmp_path / "sessions"
    SessionStore(root).save(payload)
    first = new_window(monkeypatch, root)
    assert len(first.final_selections) == 1
    assert first.acceptance_report.ready
    assert first.export_panel.export.isEnabled()
    close_window(first)

    manifest_path.unlink()
    second = new_window(monkeypatch, root)
    assert second.final_selections == ()
    assert not second.acceptance_report.ready
    assert not second.export_panel.export.isEnabled()
    assert "cần duyệt lại" in second.workflow_status.text()
    close_window(second)


def test_gui_workflow_reference_never_restores_analysis_or_approval(tmp_path, monkeypatch):
    _state, _media, result = fixture_workflow(tmp_path, monkeypatch)
    refs = session_workflow.capture_workflow_refs("sample-project", result)
    assert len(refs) == 1
    payload = sample()
    payload["workflow_refs"] = list(refs)
    root = tmp_path / "sessions"
    SessionStore(root).save(payload)
    window = new_window(monkeypatch, root)
    assert window._session_lifecycle.workflow_refs == list(refs)
    assert window.workflow_results == {}
    assert window.final_selections == ()
    assert not window.acceptance_report.ready
    assert not window.export_panel.export.isEnabled()
    close_window(window)
