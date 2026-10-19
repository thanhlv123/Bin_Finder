from pathlib import Path
from types import SimpleNamespace

import pytest

from bin_finder.clips.extractor import ClipExtractionError, FfmpegClipExtractor
from bin_finder.clips.models import ClipProposal


def proposal(source_path, accepted=True):
    return ClipProposal(
        unit_id="u1",
        source_path=str(source_path),
        start=3.5,
        end=8.5,
        score=0.9,
        accepted=accepted,
        reason="target-window" if accepted else "shot-too-short",
    )


def test_build_command_defaults_to_no_overwrite_and_accurate_reencode(tmp_path: Path):
    source = tmp_path / "input.mp4"
    output = tmp_path / "output.mp4"
    extractor = FfmpegClipExtractor(executable="ffmpeg.exe")

    command = extractor.build_command(proposal(source), output)

    assert command[0] == "ffmpeg.exe"
    assert "-n" in command
    assert "-ss" in command
    assert "3.500" in command
    assert "-t" in command
    assert "5.000" in command
    assert "libx264" in command
    assert command[-1] == str(output)


def test_stream_copy_mode_is_available(tmp_path: Path):
    source = tmp_path / "input.mp4"
    output = tmp_path / "output.mp4"
    command = FfmpegClipExtractor(
        executable="ffmpeg.exe",
        reencode=False,
    ).build_command(proposal(source), output)

    assert command[-3:-1] == ["-c", "copy"]


def test_rejected_proposal_is_not_extractable(tmp_path: Path):
    extractor = FfmpegClipExtractor(executable="ffmpeg.exe")
    with pytest.raises(ClipExtractionError, match="not accepted"):
        extractor.build_command(
            proposal(tmp_path / "input.mp4", accepted=False),
            tmp_path / "out.mp4",
        )


def test_extract_refuses_existing_output_without_overwrite(tmp_path: Path):
    source = tmp_path / "input.mp4"
    output = tmp_path / "output.mp4"
    source.write_bytes(b"input")
    output.write_bytes(b"existing")

    with pytest.raises(ClipExtractionError, match="đã tồn tại"):
        FfmpegClipExtractor(executable="ffmpeg.exe").extract(
            proposal(source),
            output,
        )


def test_extract_returns_result_after_successful_ffmpeg_call(tmp_path: Path, monkeypatch):
    source = tmp_path / "input.mp4"
    output = tmp_path / "nested" / "output.mp4"
    source.write_bytes(b"input")

    def fake_run(command, **kwargs):
        Path(command[-1]).write_bytes(b"rendered")
        assert kwargs.get("check") is False
        assert "shell" not in kwargs
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "bin_finder.clips.extractor.subprocess.run",
        fake_run,
    )

    result = FfmpegClipExtractor(executable="ffmpeg.exe").extract(
        proposal(source),
        output,
    )

    assert result.output_path == str(output)
    assert result.bytes_written == len(b"rendered")
    assert result.duration == 5.0
