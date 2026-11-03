"""Offline acceptance for project-scoped YouTube footage reuse."""
from dataclasses import replace
import io
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from bin_finder.brief.models import Cue
from bin_finder.footage.config import FootageConfig
from bin_finder.footage.youtube_clips import YouTubeClips
from bin_finder.footage.youtube_usage import violations, save_usage, read_usage, usage_context
from bin_finder.footage.youtube_vlm import parse_frame, frame_prompt
from bin_finder.matching import MatchConfig, select_footage
from bin_finder.production import MissingSelectionError, ProductionError
from bin_finder.production.config import ProductionConfig
from bin_finder.production.media import acquire_media, probe_media
from bin_finder.production.timeline import Shot, Timeline, resolve_selections
from bin_finder.production.youtube_transform import (
    YouTubeTransformConfig, crop_avoiding, intersects, plan_transform, rotation_zoom,
    transform_filter, transform_shot,
)
from bin_finder.qa.checks import check_media
from bin_finder.verification.ollama_vlm import VlmResponseError

FFMPEG = shutil.which("ffmpeg")


def region(kind: str, box: list[float]) -> dict:
    return {"kind": kind, "box": box}


def youtube(video_id: str = "video", start: float = 100, channel: str = "channel") -> dict:
    return {"video_id": video_id, "channel": channel, "channel_id": channel,
            "url": f"https://www.youtube.com/watch?v={video_id}", "start": start, "end": start + 4,
            "storyboard_score": 0.95, "regions": [], "scene_drift": False}


def candidate(video_id: str = "video", start: float = 100) -> dict:
    evidence = youtube(video_id, start)
    return {"source_id": f"youtube:{video_id}:{start}", "provider": "youtube", "title": "Red sunrise landscape",
            "description": "Red sunrise landscape", "duration": 4, "resolution": "1920x1080",
            "reference_only": False, "youtube": evidence, "thumbnail_url": "", "preview_url": "", "source_url": evidence["url"],
            "license": {"kind": "youtube_reuse", "usable_in_video": True, "requires_transform": True,
                        "source_url": evidence["url"], "license_name": "YouTube reuse", "creator": "channel"}}


def shot_for(evidence: dict | None = None) -> Shot:
    evidence = evidence or youtube()
    shot = Shot("cue", "Red sunrise.", 0, 4, "youtube:clip", "youtube", "clip.mp4", "selected",
                {"kind": "youtube_reuse", "usable_in_video": True,
                 "license_name": "YouTube reuse", "source_url": evidence["url"]}, clip_out=4,
                youtube=evidence)
    plan = plan_transform(evidence["regions"], shot.cue_id, YouTubeTransformConfig())
    for name in ("transforms", "zoom", "rotate", "mirrored", "blurred_regions"):
        setattr(shot, name, plan[name])
    shot.youtube["crop"] = plan["crop"]
    return shot


def test_opt_in_config(tmp_path, monkeypatch):
    assert not FootageConfig().youtube_reuse
    assert FootageConfig(youtube_reuse=True).youtube_enabled
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "footage.local.json").write_text(json.dumps({"youtube_reuse": True}))
    assert FootageConfig.load(tmp_path).youtube_reuse
    monkeypatch.setenv("BIN_FINDER_FOOTAGE_YOUTUBE_REUSE", "false")
    assert not FootageConfig.load(tmp_path).youtube_reuse
    monkeypatch.setenv("BIN_FINDER_PROD_YT_MIN_ZOOM", "1.15")
    monkeypatch.setenv("BIN_FINDER_PROD_YT_MIRROR", "false")
    config = ProductionConfig.load(tmp_path)
    assert config.youtube_transform.min_zoom == 1.15
    assert not config.youtube_transform.mirror


@pytest.mark.parametrize("name", ["max_workers", "frames_per_video", "videos_per_cue", "window_seconds"])
def test_positive_limits(name):
    with pytest.raises(ValueError):
        FootageConfig(**{name: 0})


@pytest.mark.parametrize("box", [[0.9, 0, 0.1, 0.1], [0.8, 0.02, 0.15, 0.08], [0.01, 0.9, 0.1, 0.1]])
def test_crop_corner_watermark(box):
    crop = crop_avoiding([region("channel_watermark", box)])
    assert not intersects(crop, box)
    assert 1.08 - 1e-7 <= 1 / crop[2] <= 1.4 + 1e-7
    assert crop[2] == pytest.approx(crop[3])


def test_crop_bottom_text_and_center_rejections():
    bottom = region("burned_subtitles", [0, 0.9, 1, 0.1])
    plan = plan_transform([bottom], "cue", YouTubeTransformConfig())
    assert not plan["blurred_regions"]
    central = [0.4, 0.4, 0.2, 0.2]
    with pytest.raises(ProductionError, match="watermark"):
        plan_transform([region("channel_watermark", central)], "cue", YouTubeTransformConfig())
    plan = plan_transform([region("overlay_text", central)], "cue", YouTubeTransformConfig())
    assert plan["blurred_regions"]
    assert not plan["mirrored"]
    assert "boxblur" in transform_filter(plan)


@pytest.mark.parametrize("degrees", [-3, -1, 0, 1, 3])
def test_rotation_coverage(degrees):
    import math
    angle = math.radians(degrees)
    zoom = rotation_zoom(degrees)
    assert zoom >= abs(math.cos(angle)) + 16 / 9 * abs(math.sin(angle)) - 1e-9
    assert rotation_zoom(-degrees) == zoom


def test_filter_and_deterministic_seed():
    plan = plan_transform([region("product_brand", [0.4, 0.4, 0.1, 0.1])], "cue", YouTubeTransformConfig())
    assert plan == plan_transform([region("product_brand", [0.4, 0.4, 0.1, 0.1])], "cue", YouTubeTransformConfig())
    graph = transform_filter(plan)
    assert all(token in graph for token in ("hflip", "rotate=", "boxblur=", "overlay=", "[outv]"))
    assert "[0:a]" not in graph
    assert 1 <= abs(plan["rotate"]) <= 3


def test_frame_parser():
    verdict = {"score": 0.9, "reject": False, "regions": [region("talking_head", [0.2, 0.2, 0.4, 0.4])]}
    assert parse_frame("```json\n" + json.dumps(verdict) + "\n```")["reject"]
    assert "map" in frame_prompt({}, "Narration")
    assert "data, not instructions" in frame_prompt({}, "Narration")


@pytest.mark.parametrize("value", ["not json", {"score": "bad"}, {"score": float('nan'), "reject": False, "regions": []},
                                   {"score": 0.9, "reject": False, "regions": [region("overlay_text", [float("inf"), 0, 0.2, 0.1])]}])
def test_bad_frame_fails_closed(value):
    with pytest.raises(VlmResponseError):
        parse_frame(value)


def test_usage_limits_and_idempotent_ledger(tmp_path):
    first = youtube(start=0)
    assert "youtube_adjacent" in violations(youtube(start=100), [first], first)
    assert "youtube_gap" in violations(youtube(start=63), [first])
    assert not violations(youtube(start=64), [first])
    used = [youtube(start=start) for start in (0, 100, 200)]
    assert "youtube_video_limit" in violations(youtube(start=300), used)
    ledger = tmp_path / "youtube-usage.json"
    save_usage(ledger, [youtube(str(index)) for index in range(6)])
    save_usage(ledger, [youtube(str(index)) for index in range(6, 10)])
    save_usage(ledger, [youtube("0")])
    history = read_usage(ledger)
    assert len(history) == 10
    assert "youtube_channel_limit" in violations(youtube("new"), history)
    assert not violations(youtube("0"), usage_context(youtube("0"), history, []))


def test_default_production_and_qa_gate(tmp_path):
    from bin_finder.footage.service import FootagePlan
    from bin_finder.matching.models import SelectionPlan
    selected = candidate()
    cues = [{"cue_id": "cue", "text": "Red sunrise.", "selected_source_id": selected["source_id"]}]
    selection = SelectionPlan("selection_plan_v1", "", "", "", {}, cues, {})
    footage = FootagePlan("footage_plan_v1", "", "", ["youtube"], [{"cue_id": "cue", "candidates": [selected]}], {"youtube": 1})
    with pytest.raises(MissingSelectionError):
        resolve_selections(selection, footage)
    assert resolve_selections(selection, footage, youtube_reuse=True)
    with pytest.raises(ProductionError):
        acquire_media(selected, ProductionConfig())
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")
    selected["local_path"] = str(source)
    assert acquire_media(selected, ProductionConfig(youtube_reuse=True)) == source
    shot = shot_for()
    timeline = Timeline([shot], 4, [])
    assert any(finding.code == "unusable_license" and finding.severity == "blocker" for finding in check_media(timeline, shot.license["source_url"]))
    timeline.youtube_reuse = True
    findings = check_media(timeline, shot.license["source_url"])
    assert any(finding.code == "youtube_reuse" and finding.severity == "warning" for finding in findings)
    assert not any(finding.severity == "blocker" for finding in findings)
    shot.transforms = []
    assert any(finding.code == "youtube_untransformed" for finding in check_media(timeline, shot.license["source_url"]))
    shot.youtube["regions"] = [region("channel_watermark", [0.4, 0.4, 0.1, 0.1])]
    assert any(finding.code == "youtube_watermark" for finding in check_media(timeline, shot.license["source_url"]))


def test_qa_actual_source_limits():
    shots = [shot_for(youtube(start=start)) for start in (0, 20, 100, 200)]
    timeline = Timeline(shots, 16, [], youtube_reuse=True)
    codes = {finding.code for finding in check_media(timeline, "https://www.youtube.com/watch?v=video")}
    assert {"youtube_adjacent", "youtube_gap", "youtube_video_limit"} <= codes
    timeline.shots = [shot_for(youtube(str(index))) for index in range(11)]
    assert "youtube_channel_limit" in {finding.code for finding in check_media(timeline, "credits")}


class FakeJudge:
    def __init__(self, drift: bool = False):
        self.calls = 0
        self.drift = drift

    def inspect(self, brief, cue_text, image, thumbnail=True):
        self.calls += 1
        return {"score": 0.2 if self.drift and self.calls == 3 else 0.95, "regions": [], "reject": False}


class FakeOpener:
    def __init__(self, image: bytes):
        self.image = image
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        assert request.full_url.startswith("https://i.ytimg.com/")
        return io.BytesIO(self.image)


class FakeRunner:
    def __init__(self, media: Path):
        self.media = media
        self.calls = []

    def __call__(self, arguments, **kwargs):
        self.calls.append(arguments)
        if arguments[0] != "fake-yt-dlp":
            return subprocess.run(arguments, **kwargs)
        if "--flat-playlist" in arguments:
            entries = [{"id": "short", "duration": 10}, {"id": "long", "duration": 11000},
                       {"id": "shorturl", "duration": 90, "url": "https://www.youtube.com/shorts/shorturl"},
                       {"id": "video", "duration": 120}]
            return SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(entry) for entry in entries).encode())
        if "--download-sections" in arguments:
            shutil.copyfile(self.media, arguments[arguments.index("-o") + 1])
            return SimpleNamespace(returncode=0, stdout=b"")
        info = {"id": "video", "duration": 120, "title": "Red sunrise landscape", "channel": "channel", "channel_id": "channel",
                "description": "Red sunrise landscape", "width": 320, "height": 180,
                "license": "Creative Commons Attribution license", "formats": [
                    {"format_id": "sb0", "width": 80, "height": 45},
                    {"format_id": "sb1", "width": 160, "height": 90, "rows": 2, "columns": 2, "fps": 1 / 30,
                     "fragments": [{"url": "https://i.ytimg.com/storyboard.jpg?secret=signed", "duration": 120}]}]}
        return SimpleNamespace(returncode=0, stdout=json.dumps(info).encode())


@pytest.fixture
def local_media(tmp_path):
    if not FFMPEG:
        pytest.skip("ffmpeg is unavailable")
    media = tmp_path / "source.mp4"
    image = tmp_path / "grid.jpg"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=red:s=320x180:r=10:d=8",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=8", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(media)], check=True, capture_output=True)
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(media), "-frames:v", "1", str(image)], check=True, capture_output=True)
    return media, image.read_bytes()


def test_keyless_acquisition_cache_and_transform(tmp_path, local_media):
    media, image = local_media
    runner = FakeRunner(media)
    opener = FakeOpener(image)
    config = FootageConfig(youtube_reuse=True, yt_dlp="fake-yt-dlp", ffmpeg=FFMPEG,
                           frames_per_video=2, cache_dir=str(tmp_path / "cache"), usage_dir=str(tmp_path))
    service = YouTubeClips(config, runner=runner, opener=opener, judge=FakeJudge())
    cue = Cue("cue", "", "Red sunrise landscape", 3, 4)
    candidates, warnings = service.search(cue, {}, ["red sunrise"])
    assert not warnings
    assert len(candidates) == 1
    selected = candidates[0]
    assert selected["license"]["requires_transform"]
    assert not selected["reference_only"]
    assert Path(selected["local_path"]).is_file()
    assert probe_media(Path(selected["local_path"])).duration == pytest.approx(4, abs=0.2)
    assert opener.calls == 1
    assert "secret" not in (tmp_path / "cache/video.info.json").read_text()
    candidates_again, warnings = service.search(cue, {}, ["red sunrise"])
    assert candidates_again and not warnings
    assert opener.calls == 1
    assert sum("--download-sections" in call for call in runner.calls) == 1
    assert sum("--skip-download" in call for call in runner.calls) == 1
    shot = shot_for(selected["youtube"])
    shot.local_path = selected["local_path"]
    shot.youtube["regions"] = [region("product_brand", [0.4, 0.4, 0.2, 0.2])]
    output = tmp_path / "transformed.mp4"
    transform_shot(shot, output, ProductionConfig(ffmpeg=FFMPEG, width=320, height=180), 320, 180)
    metadata = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)], check=True, capture_output=True).stdout)
    assert [stream["codec_type"] for stream in metadata["streams"]] == ["video"]
    assert shot.transforms and shot.blurred_regions


def test_drift_tries_next_frame(tmp_path, local_media):
    media, image = local_media
    config = FootageConfig(youtube_reuse=True, yt_dlp="fake-yt-dlp", ffmpeg=FFMPEG,
                           frames_per_video=2, cache_dir=str(tmp_path / "cache"))
    judge = FakeJudge(drift=True)
    service = YouTubeClips(config, runner=FakeRunner(media), opener=FakeOpener(image), judge=judge)
    candidates, warnings = service.search(Cue("cue", "", "Red sunrise landscape", 3, 4), {}, ["sunrise"])
    assert candidates
    assert any("scene_drift" in warning for warning in warnings)
    assert judge.calls >= 5


def test_bad_video_does_not_stop_search(tmp_path):
    def fail(arguments, **kwargs):
        if "--flat-playlist" in arguments:
            return SimpleNamespace(returncode=0, stdout=b'{"id":"broken","duration":120}')
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"private-secret")
    service = YouTubeClips(FootageConfig(cache_dir=str(tmp_path)), runner=fail, judge=FakeJudge())
    candidates, warnings = service.search(Cue("cue", "", "sunrise", 1, 4), {}, ["sunrise"])
    assert not candidates
    assert warnings == ["YouTube broken: info/storyboard unavailable"]


def test_matching_storyboard_without_thumbnail_and_limits(tmp_path):
    from bin_finder.brief import BriefPlan
    from bin_finder.footage.service import FootagePlan
    from test_matching_selector import inputs
    _, briefs = inputs()
    first = candidate("one", 0)
    first.update(title="A doctor reads a report", description="A doctor reads a report", thumbnail_url="https://unneeded")
    second = candidate("one", 100)
    second.update(title=first["title"], description=first["description"])
    alternative = candidate("two", 100)
    alternative.update(title=first["title"], description=first["description"])
    cues = [{"cue_id": "C0001", "text": "A doctor reads a report.", "candidates": [first]},
            {"cue_id": "C0002", "text": "A doctor reads a report.", "candidates": [second, alternative]}]
    footage = FootagePlan("footage_plan_v1", "", "", ["youtube"], cues, {"youtube": 3}, youtube_reuse=True)
    def forbidden(*args):
        raise AssertionError("Thumbnail should not be fetched")
    selection = select_footage(footage, briefs, MatchConfig(), judge=object(), fetch=forbidden)
    assert [cue["selected_source_id"] for cue in selection.cues] == [first["source_id"], alternative["source_id"]]
    assert selection.stats["thumbnail_fetched"] == 0
    assert selection.stats["vlm_calls"] == 0
    assert selection.cues[0]["ranked"][0]["vlm"]["score"] == 0.95
    ledger = tmp_path / "youtube-usage.json"
    save_usage(ledger, [youtube(str(index), channel="channel") for index in range(10)])
    footage = replace(footage, youtube_usage_path=str(ledger))
    selection = select_footage(footage, briefs, MatchConfig(), judge=object(), fetch=forbidden)
    assert all(cue["selected_source_id"] is None for cue in selection.cues)


def test_production_auto_fallback_and_locked_rejection():
    from bin_finder.footage.service import FootagePlan
    from bin_finder.matching.models import SelectionPlan
    bad = candidate("bad")
    bad["youtube"]["regions"] = [region("channel_watermark", [0.4, 0.4, 0.2, 0.2])]
    good = candidate("good")
    cue = {"cue_id": "cue", "text": "Red sunrise.", "selected_source_id": bad["source_id"],
           "selection_origin": "auto", "status": "auto_selected", "ranked": [bad, good]}
    selection = SelectionPlan("selection_plan_v1", "", "", "", {}, [cue], {})
    footage = FootagePlan("footage_plan_v1", "", "", ["youtube"], [{"cue_id": "cue", "candidates": [bad, good]}], {})
    assert resolve_selections(selection, footage, youtube_reuse=True)[0]["candidate"] == good
    cue.update(selected_source_id=bad["source_id"], status="locked")
    with pytest.raises(MissingSelectionError):
        resolve_selections(selection, footage, youtube_reuse=True)


def test_run_cli_all_steps_and_switch_resume(tmp_path, monkeypatch):
    from bin_finder.run.cli import main
    from bin_finder.run.steps import read_json
    from test_run_pipeline import services_for
    script = tmp_path / "script.txt"
    script.write_text("Red sunrise.")
    output = tmp_path / "out"
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake-source")
    class Service:
        def __init__(self, config):
            self.usage_path = Path(config.usage_dir) / "youtube-usage.json"

        def search(self, cue, brief, queries):
            return [{**candidate(), "local_path": str(source), "candidate_id": cue.cue_id + ":youtube", "scene_id": cue.cue_id}], []
    def transform(shot, destination, config, width, height):
        plan = plan_transform(shot.youtube["regions"], shot.cue_id, config.youtube_transform)
        for name in ("transforms", "zoom", "rotate", "mirrored", "blurred_regions"):
            setattr(shot, name, plan[name])
        shot.youtube["crop"] = plan["crop"]
    monkeypatch.setattr("bin_finder.production.youtube_transform.transform_shot", transform)
    services = replace(services_for(tmp_path), youtube_service_factory=Service)
    config = tmp_path / "run.json"
    config.write_text(json.dumps({"brief": {"provider": "heuristic"}, "footage": {"sources": []}}))
    arguments = [str(script), "-o", str(output), "--project-root", str(tmp_path), "--config", str(config)]
    assert main([*arguments, "--youtube-reuse"], services=services) == 0
    manifest = read_json(output / "production.json")
    assert manifest["youtube_reuse"]
    assert manifest["shots"][0]["transforms"]
    assert len(read_json(output / "youtube-usage.json")) == 1
    credits = (output / "credits.txt").read_text(encoding="utf-8")
    assert "YouTube\n" in credits
    assert "&t=100s" in credits
    assert "remove_audio" in credits
    assert main([*arguments, "--youtube-reuse", "--resume"], services=services) == 0
    assert all(step["status"] == "skipped" for step in read_json(output / "run-state.json")["steps"])
    config.write_text(json.dumps({"brief": {"provider": "heuristic"}, "footage": {"sources": ["pexels"]}}))
    assert main([*arguments, "--no-youtube-reuse", "--resume"], services=services) == 0
    steps = read_json(output / "run-state.json")["steps"]
    assert steps[0]["status"] == "skipped"
    assert all(step["status"] == "done" for step in steps[1:])
    assert not read_json(output / "production.json")["youtube_reuse"]


def test_resume_invalidates_from_footage_only(tmp_path):
    from bin_finder.run import run_pipeline
    from bin_finder.run.steps import read_json
    from test_run_pipeline import setup_run
    script, output, options, services = setup_run(tmp_path)
    class EmptyYouTube:
        def __init__(self, config):
            self.usage_path = Path(config.usage_dir) / "youtube-usage.json"

        def search(self, *args):
            return [], []
    services = replace(services, youtube_service_factory=EmptyYouTube)
    assert run_pipeline(script, output, replace(options, youtube_reuse=False), services=services) == 0
    assert run_pipeline(script, output, replace(options, youtube_reuse=True, resume=True), services=services) == 0
    steps = read_json(output / "run-state.json")["steps"]
    assert [step["status"] for step in steps] == ["skipped", "done", "done", "done", "done", "done"]


def test_run_file_config_and_cli_override(tmp_path):
    from bin_finder.run.cli import parser, load_options
    path = tmp_path / "run.json"
    path.write_text(json.dumps({"footage": {"youtube_reuse": True}}))
    args = ["script.txt", "-o", "output", "--config", str(path)]
    assert load_options(parser().parse_args(args)).youtube_reuse is True
    assert load_options(parser().parse_args([*args, "--no-youtube-reuse"])).youtube_reuse is False
    path.write_text(json.dumps({"footage": {"youtube_reuse": "true"}}))
    with pytest.raises(ValueError):
        load_options(parser().parse_args(args))


@pytest.mark.parametrize("width,height", [(1080, 1920), (1920, 1080), (1024, 768)])
def test_crop_keeps_output_aspect(width, height):
    plan = plan_transform([], "cue", YouTubeTransformConfig(), width, height)
    crop = plan["crop"]
    assert width * crop[2] / (height * crop[3]) == pytest.approx(16 / 9)


def test_storyboard_cache_refreshes_sampling_budget(tmp_path, local_media):
    media, image = local_media
    runner = FakeRunner(media)
    config = FootageConfig(cache_dir=str(tmp_path / "cache"), yt_dlp="fake-yt-dlp", ffmpeg=FFMPEG, frames_per_video=2)
    service = YouTubeClips(config, runner=runner, opener=FakeOpener(image), judge=FakeJudge())
    assert len(service._prepare("video")["frames"]) == 2
    service = YouTubeClips(replace(config, frames_per_video=3), runner=runner, opener=FakeOpener(image), judge=FakeJudge())
    assert len(service._prepare("video")["frames"]) == 3
    assert sum("--skip-download" in call for call in runner.calls) == 2


@pytest.mark.parametrize("score,reuse,drift,expected", [(0.7, True, False, "youtube"), (0.3, True, False, "stock"), (0.7, False, False, "stock"), (0.9, True, True, "stock")])
def test_youtube_preference_against_stock(monkeypatch, score, reuse, drift, expected):
    from bin_finder.brief import BriefPlan
    from bin_finder.footage.service import FootagePlan
    from bin_finder.matching.vlm_score import VisualVerdict
    from bin_finder.matching import selector

    selected = candidate()
    selected["youtube"].update(storyboard_score=score, scene_drift=drift)
    stock = {**selected, "provider": "pexels", "source_id": "stock", "youtube": None,
             "thumbnail_url": "https://images.pexels.com/test.jpg", "license": {"usable_in_video": True}}
    monkeypatch.setattr(selector, "score_candidates", lambda brief, text, candidates: [SimpleNamespace(candidate=item, text_score=0.7 if item["provider"] == "pexels" else 0.0, reasons=[]) for item in candidates])
    judge = SimpleNamespace(judge=lambda *args: VisualVerdict("match", 0.7, "Verified", False))
    cues = [{"cue_id": "cue", "text": "Red sunrise", "candidates": [stock, selected]}]
    footage = FootagePlan("footage_plan_v1", "", "", [], cues, {}, youtube_reuse=reuse)
    selection = select_footage(footage, BriefPlan([], [], "heuristic", 0, ""), MatchConfig(), judge, lambda *args: b"image")
    row = selection.cues[0]
    assert row["selected_source_id"] == (selected["source_id"] if expected == "youtube" else "stock")
    youtube_row = next(item for item in row["ranked"] if item["provider"] == "youtube")
    assert youtube_row["youtube_preferred"] == (reuse and not drift and score >= 0.7)
    if youtube_row["youtube_preferred"]:
        assert youtube_row["final_score"] == 0.8
