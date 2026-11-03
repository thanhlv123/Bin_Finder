import json
from pathlib import Path
import pytest
from bin_finder.brief import BriefConfig
import bin_finder.brief


def test_defaults(tmp_path):
    config = BriefConfig.load(tmp_path)
    assert config.provider == "auto"
    assert config.batch_size == 6
    assert len(config.sources) == 6


def test_local_and_env(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/planning.local.json").write_text(json.dumps({"provider":"ollama", "batch_size":3,"api_key":"secret"}))
    monkeypatch.setenv("BIN_FINDER_PLANNING_BATCH_SIZE", "2")
    monkeypatch.setenv("BIN_FINDER_PLANNING_TIMEOUT_SEC", "12.5")
    monkeypatch.setenv("BIN_FINDER_PLANNING_SOURCES", "pexels,commons")
    config = BriefConfig.load(tmp_path)
    assert config.provider == "ollama" and config.batch_size == 2
    assert config.timeout_sec == 12.5 and config.sources == ["pexels", "commons"]
    assert "secret" not in repr(config)
    monkeypatch.setenv("BIN_FINDER_PLANNING_SOURCES", '["youtube"]')
    assert BriefConfig.load(tmp_path).sources == ["youtube"]


def test_no_fixed_paths():
    for p in Path(bin_finder.brief.__file__).parent.glob("*.py"):
        text = p.read_text(encoding="utf-8")
        assert not any(s in text for s in ["Cuba15", "production_control_root", "D:/", "C:/"])


@pytest.mark.parametrize("kwargs", [{"batch_size":0}, {"timeout_sec":float("nan")}, {"provider":"bad"}, {"sources":[]}])
def test_invalid_settings(kwargs):
    with pytest.raises(ValueError):
        BriefConfig(**kwargs)
