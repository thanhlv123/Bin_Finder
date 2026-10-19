from pathlib import Path

from bin_finder.analysis.transcript import (
    find_transcript_sidecar,
    load_transcript_sidecar,
    parse_timed_transcript,
)


def test_parse_srt_and_strip_simple_tags():
    transcript = parse_timed_transcript(
        """1
00:00:01,000 --> 00:00:03,250
<i>Hello Havana</i>

2
00:00:04,000 --> 00:00:06,000
Classic car mechanic
"""
    )
    assert len(transcript) == 2
    assert transcript[0].start == 1.0
    assert transcript[0].end == 3.25
    assert transcript[0].text == "Hello Havana"
    assert transcript[1].text == "Classic car mechanic"


def test_parse_webvtt():
    transcript = parse_timed_transcript(
        """WEBVTT

00:00:00.500 --> 00:00:02.000
Airport family goodbye
"""
    )
    assert transcript[0].start == 0.5
    assert transcript[0].end == 2.0


def test_exact_sidecar_is_preferred(tmp_path: Path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"video")
    language_sidecar = tmp_path / "clip.en.srt"
    language_sidecar.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nEnglish\n",
        encoding="utf-8",
    )
    exact = tmp_path / "clip.srt"
    exact.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nExact\n",
        encoding="utf-8",
    )

    assert find_transcript_sidecar(media) == exact
    path, transcript = load_transcript_sidecar(media)
    assert path == exact
    assert transcript[0].text == "Exact"
