from __future__ import annotations

import hashlib
import re
from pathlib import Path

from bin_finder.analysis.models import TranscriptSegment


_TIME_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})"
)


def _seconds(value: str) -> float:
    normalized = value.replace(",", ".")
    hours, minutes, seconds = normalized.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_timed_transcript(text: str) -> tuple[TranscriptSegment, ...]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[TranscriptSegment] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        match = _TIME_RE.search(line)
        if not match:
            index += 1
            continue
        start = _seconds(match.group("start"))
        end = _seconds(match.group("end"))
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].strip():
            current = lines[index].strip()
            if not current.isdigit():
                body.append(current)
            index += 1
        content = " ".join(body).strip()
        content = re.sub(r"<[^>]+>", "", content).strip()
        if content and end > start:
            segments.append(TranscriptSegment(start=start, end=end, text=content))
        index += 1
    return tuple(segments)


def find_transcript_sidecar(media_path: str | Path) -> Path | None:
    path = Path(media_path)
    exact = [path.with_suffix(".srt"), path.with_suffix(".vtt")]
    for candidate in exact:
        if candidate.exists() and candidate.is_file():
            return candidate
    matches = sorted(
        [
            *path.parent.glob(f"{path.stem}*.srt"),
            *path.parent.glob(f"{path.stem}*.vtt"),
        ],
        key=lambda item: item.name.casefold(),
    )
    return next((item for item in matches if item.is_file()), None)


def transcript_sha256(path: Path | None) -> str:
    if path is None:
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(256 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def load_transcript_sidecar(
    media_path: str | Path,
) -> tuple[Path | None, str, tuple[TranscriptSegment, ...]]:
    sidecar = find_transcript_sidecar(media_path)
    if sidecar is None:
        return None, "", ()
    digest = transcript_sha256(sidecar)
    text = sidecar.read_text(encoding="utf-8-sig", errors="replace")
    return sidecar, digest, parse_timed_transcript(text)
