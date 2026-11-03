"""Headless production with injected offline service boundaries."""
import json
from pathlib import Path

from bin_finder.production.__main__ import main
from bin_finder.production.media import MediaInfo
from test_production_tts import FakeEngine

FIXTURES = Path(__file__).parent / "fixtures/production"


def arguments(tmp_path):
    return [str(FIXTURES / "selection.json"), "--footage", str(FIXTURES / "footage.json"),
            "-o", str(tmp_path / "out.mp4"), "--project-root", str(tmp_path)]


def test_dry_run_no_services(tmp_path, capsys):
    def forbidden(*values):
        raise AssertionError("Service called during dry-run")

    assert main([*arguments(tmp_path), "--dry-run"], engine=forbidden,
                media_loader=forbidden, renderer=forbidden) == 0
    assert "Dry run: 3 cues" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_missing_returns_two_before_tts(tmp_path, capsys):
    selection = json.loads((FIXTURES / "selection.json").read_text())
    selection["cues"][0]["selected_source_id"] = None
    source = tmp_path / "selection.json"
    source.write_text(json.dumps(selection))
    command = arguments(tmp_path)
    command[0] = str(source)
    engine = FakeEngine()
    assert main(command, engine=engine) == 2
    assert "cue-1: Red sunrise." in capsys.readouterr().err
    assert engine.calls == 0
    assert not (tmp_path / "out_work").exists()


def test_complete_cli_injected(tmp_path):
    engine = FakeEngine()
    acquired = []

    def loader(candidate, config):
        acquired.append(candidate["source_id"])
        return tmp_path / (candidate["source_id"].replace(":", "_") + ".mp4")

    def renderer(timeline, narration, output, work_dir, config):
        assert narration.is_file()
        assert config.subtitles
        assert config.subscribe_icon
        output.write_bytes(b"fake rendered artifact")

    assert main(arguments(tmp_path), engine=engine, media_loader=loader,
                media_probe=lambda *values: MediaInfo(6, 1920, 1080), renderer=renderer) == 0
    assert len(acquired) == 3
    assert engine.calls == 1
    timeline = json.loads((tmp_path / "production.json").read_text())
    assert len(timeline["shots"]) == 3
    assert timeline["duration"] == 5
    assert "Voice: VoiceStudio (The Documentarian)" in (tmp_path / "credits.txt").read_text(encoding="utf-8")


def test_cli_decisions(tmp_path):
    command = [*arguments(tmp_path), "--dry-run", "--decisions", str(FIXTURES / "decisions.json"), "--limit-cues", "1"]
    assert main(command) == 0
