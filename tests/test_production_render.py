"""Real local FFmpeg smoke and pure transition/media planning tests."""
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from bin_finder.production import ProductionError
from bin_finder.production.config import ProductionConfig
from bin_finder.production.media import MediaInfo, plan_clip, probe_media, rendition_url
from bin_finder.production.render import assembly_filter, render_video, transition_durations
from bin_finder.production.timeline import Shot, Timeline
from bin_finder.production.tts import wav_duration


def color_timeline():
    shots = [Shot(f"cue-{index}", text, start, end, f"source-{index}", "pexels", "", "selected", {})
             for index, (text, start, end) in enumerate([("Red sun", 0, 1), ("Green tree", 1, 2), ("Blue sea", 2, 5)])]
    words = [dict(word=text, start=index * 0.4, end=index * 0.4 + 0.35)
             for index, text in enumerate("Red sun green tree blue sea".split())]
    return Timeline(shots, 5, words)


def test_xfade_offsets_do_not_shorten_voice():
    timeline = color_timeline()
    transitions = transition_durations(timeline, ProductionConfig())
    graph, label = assembly_filter(timeline, transitions)
    assert "duration=0.400000:offset=1.000000" in graph
    assert "duration=0.400000:offset=2.000000" in graph
    assert label == "join2"
    assert sum(shot.end - shot.start + transition for shot, transition in zip(timeline.shots, transitions)) - sum(transitions) == 5
    timeline.shots[1].source_id = timeline.shots[0].source_id
    transitions = transition_durations(timeline, ProductionConfig())
    assert transitions[0] == 0
    assert "concat=n=2" in assembly_filter(timeline, transitions)[0]


def test_short_clip_and_no_overlap():
    shot = color_timeline().shots[0]
    plan_clip(shot, {}, MediaInfo(2, 1920, 1080), 5)
    assert shot.speed == 0.8
    assert shot.clip_out == 2
    assert any("final frame" in note for note in shot.notes)
    with pytest.raises(ProductionError, match="non-overlapping"):
        plan_clip(shot, {}, MediaInfo(2, 1920, 1080), 5, used_until=2)


@pytest.mark.parametrize("metadata", [
    {"video_files": [{"link": "https://cdn.example/low", "width": 1280, "height": 720}, {"link": "https://cdn.example/full", "width": 1920, "height": 1080}]},
    {"videos": {"medium": {"url": "https://cdn.example/low", "width": 1280, "height": 720}, "large": {"url": "https://cdn.example/full", "width": 1920, "height": 1080}}},
    {"renditions": [{"url": "https://cdn.example/full", "width": 1920, "height": 1080}]},
    {"urls": {"mp4_download": "https://cdn.example/full"}},
    {"original_url": "https://cdn.example/full"},
])
def test_provider_renditions(metadata):
    assert rendition_url(dict(source_metadata=metadata)) == "https://cdn.example/full"


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg not in PATH")
@pytest.mark.parametrize("with_music_and_custom_icon", [False, True])
def test_real_ffmpeg_with_subtitles_and_icon(tmp_path, with_music_and_custom_icon):
    config = ProductionConfig(subscribe_interval_sec=120)
    timeline = color_timeline()
    timeline.shots[1].block_index = 1
    for index, (shot, color, duration) in enumerate(zip(timeline.shots, ("red", "green", "blue"), (2, 4, 6))):
        source = tmp_path / f"source {index}.mp4"
        subprocess.run([config.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color=c={color}:s=320x180:r=30:d={duration}", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True)
        shot.local_path = str(source)
        extra = transition_durations(timeline, config)[index]
        plan_clip(shot, {}, probe_media(source), shot.end - shot.start + extra)
    narration = tmp_path / "voice.wav"
    subprocess.run([config.ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=3:sample_rate=24000", "-c:a", "pcm_s16le", str(narration)],
                   check=True, capture_output=True)
    if with_music_and_custom_icon:
        from bin_finder.production.icons import write_subscribe_icon
        icon_path = tmp_path / "custom icon.png"
        write_subscribe_icon(icon_path)
        config = replace(config, music_path=str(narration), whoosh_path=str(narration),
                         pop_path=str(narration), subscribe_icon_path=str(icon_path),
                         leak_path=timeline.shots[0].local_path)
    # Keep first icon at 30 s in production; exercise the same filter at 1 s here.
    from unittest.mock import patch
    output = tmp_path / "final video.mp4"
    with patch("bin_finder.production.render.icon_times", return_value=[1.0]):
        render_video(timeline, narration, output, tmp_path / "work space", config)
    info = probe_media(output)
    assert (info.width, info.height) == (1920, 1080)
    assert info.duration == pytest.approx(wav_duration(narration.read_bytes()) + config.end_hold, abs=0.15)
    result = subprocess.run([config.ffprobe, "-v", "error", "-show_streams", "-of", "json", str(output)],
                            capture_output=True, check=True)
    assert any(stream["codec_type"] == "audio" for stream in json.loads(result.stdout)["streams"])
    mix_graph = (tmp_path / "work space/mix.ffgraph").read_text()
    assert "fade=t=in" in mix_graph
    assert "scale=420" not in mix_graph
    assert "y=H-h-170" in mix_graph
    assert [shot.effects["pop"] for shot in timeline.shots] == [False, with_music_and_custom_icon, with_music_and_custom_icon]
    if not with_music_and_custom_icon:
        assert "fontsize=46" in mix_graph
    else:
        assert "colorkey=0x000000" in mix_graph
        assert "colorchannelmixer=aa=0.5" in mix_graph
        assert timeline.shots[1].effects["whoosh"]
        assert timeline.shots[1].effects["leak"]
        assert not timeline.notes
    if with_music_and_custom_icon:
        assert "sidechaincompress" in mix_graph
        assert "normalize=0" in mix_graph
        assert "adelay=1000" in mix_graph

def test_block_effect_schedule_and_icon_overlap():
    from bin_finder.production.render import plan_effects
    timeline = color_timeline()
    timeline.shots = [replace(timeline.shots[0], start=index * 10, end=(index + 1) * 10,
                              block_index=block_index, effects={})
                      for index, block_index in enumerate((0, 0, 1, 2, 3, 3, 4))]
    timeline.duration = 70
    config = ProductionConfig(whoosh_path="whoosh.wav", pop_path="pop.wav", leak_path="leak.mp4")
    assert plan_effects(timeline, config) == [20, 30, 40, 60]
    whoosh_starts = [shot.start for shot in timeline.shots if shot.effects["whoosh"]]
    assert whoosh_starts == [20, 40, 60]
    assert all(current - previous >= config.whoosh_min_gap_sec for previous, current in zip(whoosh_starts, whoosh_starts[1:]))
    assert [index for index, shot in enumerate(timeline.shots) if shot.effects["pop"]] == [3]
    assert [index for index, shot in enumerate(timeline.shots) if shot.effects["leak"]] == [2, 3, 4, 6]
    plan_effects(timeline, replace(config, subscribe_icon=False, whoosh_path=None, leak_path=None))
    assert all(not any(shot.effects.values()) for shot in timeline.shots)


@pytest.mark.parametrize("available_font", ["segoeuib.ttf", "arialbd.ttf", None])
def test_icon_font_fallback(monkeypatch, available_font):
    from bin_finder.production.render import icon_decoration
    monkeypatch.setattr(Path, "is_file", lambda path: path.name == available_font)
    decoration = icon_decoration()
    if available_font:
        assert "fontfile='C\\:/Windows/Fonts/" + available_font + "'" in decoration
    else:
        assert "fontfile=" not in decoration
    assert "fontsize=46" in decoration
    assert "x=200+(325-text_w)/2" in decoration


def test_subtitle_outline(tmp_path):
    from bin_finder.production.subtitles import write_subtitles
    output = tmp_path / "captions.ass"
    write_subtitles([], output, 1920, 1080)
    style = next(line for line in output.read_text(encoding="utf-8-sig").splitlines() if line.startswith("Style:"))
    values = style.split(",")
    assert values[2] == "60"
    assert values[15:18] == ["1", "4", "1"]
    assert values[21] == "65"


def test_negative_whoosh_gap_rejected():
    with pytest.raises(ValueError, match="whoosh_min_gap_sec"):
        ProductionConfig(whoosh_min_gap_sec=-1)

def test_mix_uses_block_schedule_for_audio(tmp_path, monkeypatch):
    from bin_finder.production.render import _mix
    timeline = color_timeline()
    timeline.shots = [replace(timeline.shots[0], start=index * 10, end=(index + 1) * 10,
                              block_index=block_index, effects={})
                      for index, block_index in enumerate((0, 0, 1, 2, 3, 3, 4))]
    timeline.duration = 70
    config = ProductionConfig(whoosh_path="whoosh.wav", subtitles=False, subscribe_icon=False)
    monkeypatch.setattr("bin_finder.production.render.run_ffmpeg", lambda *arguments: None)
    _mix(timeline, tmp_path / "voice.wav", tmp_path / "joined.mp4", tmp_path / "out.mp4", tmp_path, config)
    graph = (tmp_path / "mix.ffgraph").read_text()
    assert graph.count("adelay=") == 3
    for start in (20, 40, 60):
        assert f"adelay={start * 1000}:all=1" in graph
    assert "adelay=30000" not in graph


def test_subscribe_icon_dimensions(tmp_path):
    import struct
    from bin_finder.production.icons import write_subscribe_icon
    output = tmp_path / "subscribe.png"
    write_subscribe_icon(output)
    assert struct.unpack(">II", output.read_bytes()[16:24]) == (620, 110)
