"""Isolate user-local application data between offline regression tests."""
import pytest


@pytest.fixture(autouse=True)
def isolated_local_app_data(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
