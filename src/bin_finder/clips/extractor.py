from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from bin_finder.clips.models import ClipProposal, ExtractionResult


class ClipExtractionError(RuntimeError):
    pass


class FfmpegClipExtractor:
    def __init__(
        self,
        executable: str | None = None,
        *,
        timeout: float = 300.0,
        reencode: bool = True,
    ):
        self.executable = (
            executable
            or os.environ.get("BIN_FINDER_FFMPEG", "").strip()
            or shutil.which("ffmpeg")
            or ""
        )
        self.timeout = timeout
        self.reencode = reencode

    def build_command(
        self,
        proposal: ClipProposal,
        output_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> list[str]:
        if not proposal.accepted:
            raise ClipExtractionError(
                f"Clip proposal is not accepted: {proposal.reason}"
            )
        if proposal.duration <= 0:
            raise ClipExtractionError("Clip proposal has invalid duration.")
        if not self.executable:
            raise ClipExtractionError("FFmpeg chưa được tìm thấy trong PATH.")

        source = Path(proposal.source_path)
        destination = Path(output_path)
        command = [
            self.executable,
            "-hide_banner",
            "-nostdin",
            "-y" if overwrite else "-n",
            "-ss",
            f"{proposal.start:.3f}",
            "-i",
            str(source),
            "-t",
            f"{proposal.duration:.3f}",
        ]
        if self.reencode:
            command.extend(
                [
                    "-map",
                    "0:v:0?",
                    "-map",
                    "0:a:0?",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "18",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                ]
            )
        else:
            command.extend(["-c", "copy"])
        command.append(str(destination))
        return command

    def extract(
        self,
        proposal: ClipProposal,
        output_path: str | Path,
        *,
        overwrite: bool = False,
    ) -> ExtractionResult:
        source = Path(proposal.source_path)
        destination = Path(output_path)
        if not source.exists() or not source.is_file():
            raise ClipExtractionError("Nguồn media local không tồn tại.")
        if destination.exists() and not overwrite:
            raise ClipExtractionError(
                "File đầu ra đã tồn tại và overwrite đang tắt."
            )
        destination.parent.mkdir(parents=True, exist_ok=True)

        command = self.build_command(
            proposal,
            destination,
            overwrite=overwrite,
        )
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ClipExtractionError(
                f"FFmpeg extraction failed: {exc.__class__.__name__}"
            ) from None

        if completed.returncode != 0 or not destination.exists():
            raise ClipExtractionError(
                f"FFmpeg extraction returned code {completed.returncode}."
            )
        return ExtractionResult(
            output_path=str(destination),
            bytes_written=destination.stat().st_size,
            duration=proposal.duration,
        )
