"""Offline acceptance checks for export-fixable QA blockers."""
from dataclasses import replace
from pathlib import Path

import pytest

from bin_finder.qa.models import Finding, QaReport
from bin_finder.run import run_pipeline
from bin_finder.run.steps import read_json
from test_run_pipeline import setup_run


@pytest.mark.parametrize("strict_qa", [False, True])
@pytest.mark.parametrize("codes", [("loudness",), ("loudness", "true_peak")])
def test_export_repairs_audio_blockers(tmp_path: Path, capsys, strict_qa: bool, codes: tuple[str, ...]) -> None:
    """Defer audio blockers until the exported file is evaluated."""
    script, output, options, services = setup_run(tmp_path)
    evaluated = []

    def evaluator(video: Path, *args) -> QaReport:
        evaluated.append(video.name)
        findings = [Finding(code, "blocker", "audio") for code in codes] if video.name == "video.mp4" else []
        return QaReport(str(video), "production", "now", findings)

    services = replace(services, qa_evaluator=evaluator)
    assert run_pipeline(script, output, replace(options, strict_qa=strict_qa), services=services) == 0
    assert evaluated == ["video.mp4", "final.mp4"]
    assert (output / "final.mp4").is_file()
    state = read_json(output / "run-state.json")
    assert state["steps"][4]["summary"]["blockers_fixable_by_export"] == len(codes)
    assert state["steps"][5]["status"] == "done"
    assert "Loudness sẽ được chuẩn hóa ở bước export" in capsys.readouterr().out
    assert run_pipeline(script, output, replace(options, strict_qa=strict_qa, resume=True), services=services) == 0
    assert evaluated == ["video.mp4", "final.mp4"]


def test_mixed_blockers_prevent_export(tmp_path: Path) -> None:
    """Keep visual blockers at the pre-export gate."""
    script, output, options, services = setup_run(tmp_path)

    def evaluator(video: Path, *args) -> QaReport:
        findings = [Finding(code, "blocker", "blocked") for code in ("loudness", "black_frames")]
        return QaReport(str(video), "production", "now", findings)

    def exporter(*args, **kwargs) -> None:
        pytest.fail("Export must not run with visual blockers")

    services = replace(services, qa_evaluator=evaluator, exporter=exporter)
    assert run_pipeline(script, output, options, services=services) == 3
    state = read_json(output / "run-state.json")
    assert state["status"] == "blocked"
    assert state["steps"][4]["summary"]["blockers_fixable_by_export"] == 1
    assert state["steps"][5]["status"] == "blocked"
    assert not (output / "final.mp4").exists()


def test_final_audio_blocker_removes_export(tmp_path: Path) -> None:
    """Reject and remove final media when normalization fails QA."""
    script, output, options, services = setup_run(tmp_path)
    evaluated = []

    def evaluator(video: Path, *args) -> QaReport:
        assert video.is_file()
        evaluated.append(video.name)
        return QaReport(str(video), "production", "now", [Finding("loudness", "blocker", "audio")])

    services = replace(services, qa_evaluator=evaluator)
    assert run_pipeline(script, output, options, services=services) == 3
    assert evaluated == ["video.mp4", "final.mp4"]
    assert not (output / "final.mp4").exists()
    state = read_json(output / "run-state.json")
    assert state["status"] == "blocked"
    assert state["steps"][5]["status"] == "blocked"
    assert (output / "qa-report.final.json").is_file()


@pytest.mark.parametrize("strict_qa, expected", [(True, 3), (False, 0)])
def test_no_export_audio_blocker(tmp_path: Path, strict_qa: bool, expected: int) -> None:
    """Apply strict QA to the build when export is disabled."""
    script, output, options, services = setup_run(tmp_path)

    def evaluator(video: Path, *args) -> QaReport:
        return QaReport(str(video), "production", "now", [Finding("loudness", "blocker", "audio")])

    def exporter(*args, **kwargs) -> None:
        pytest.fail("Export is disabled")

    services = replace(services, qa_evaluator=evaluator, exporter=exporter)
    options = replace(options, no_export=True, strict_qa=strict_qa)
    assert run_pipeline(script, output, options, services=services) == expected
    assert not (output / "final.mp4").exists()
