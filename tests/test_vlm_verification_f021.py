"""F021: frame sampling, local Ollama VLM provider, strict parsing, fallback and wiring.

Everything is offline: HTTP is a fake opener, FFmpeg is faked except in one guarded test.
"""
import base64
import io
import json
import math
import shutil
import subprocess
import urllib.error
from dataclasses import replace
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication
from test_final_selection_f014 import make_item  # noqa: F401  (shared offline evidence fixture)

from bin_finder.final_selection import FinalSelectionService
from bin_finder.models import SceneContext, SceneRecord
from bin_finder.retrieval import RankedSegment, RetrievalScores, RetrievalUnit
from bin_finder.verification import (
    HeuristicContextVerifier, VerificationDimensions, VerificationReranker, VerificationResult,
)
from bin_finder.verification import factory as factory_module
from bin_finder.verification import ollama_smoke
from bin_finder.verification.factory import FallbackVerificationProvider, production_verifier
from bin_finder.verification.frame_sampler import (
    FfmpegFrameSampler, FrameSamplingError, FrameSamplingPolicy, sample_times,
)
from bin_finder.verification.ollama_vlm import (
    DIMENSIONS, OllamaVisionVerifier, VlmConfig, VlmConfigError, VlmResponseError,
    build_prompt, config_from_env, parse_vlm_response, validate_loopback_url,
)

APP = QApplication.instance() or QApplication([])
JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-bytes" * 10
SCENE = SceneRecord("s1", 1, "Young workers remain at their desks late.",
                    context=SceneContext(subject=("workers",), objects=("desks",), avoid=("empty",)))
GOOD = {"subject_match": .9, "action_match": .8, "location_match": None, "object_match": .7,
        "time_match": .6, "visual_quality": .5, "context_conflict": .1, "confidence": .85,
        "explanation": "Workers at desks."}


def unit(i=1, start=2.0, end=6.0, text="workers at their desks"):
    return RetrievalUnit(f"u{i}", "D:/media/clip.mp4", start, end, metadata_text=text)


class FakeSampler:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def sample(self, path, start, end):
        self.calls.append((path, start, end))
        if len(self.calls) in self.fail:
            raise FrameSamplingError("no-frames")
        return (JPEG, JPEG, JPEG)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def envelope(payload):
    return json.dumps({"message": {"content": payload if isinstance(payload, str)
                                   else json.dumps(payload)}}).encode()


class FakeOpener:
    def __init__(self, *replies):
        self.requests, self.replies = [], list(replies)

    def open(self, request, timeout=None):
        self.requests.append((request, timeout))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return FakeResponse(reply)


def verifier(opener, sampler=None, **config):
    return OllamaVisionVerifier(VlmConfig(**config), sampler or FakeSampler(), opener)


# ---------------------------------------------------------------- frame sampling
def test_sample_times_inside_unit_and_deterministic():
    times = sample_times(2.0, 6.0, 3)
    assert times == (2.8, 4.0, 5.2) == sample_times(2.0, 6.0, 3)
    for frames in range(1, 7):
        assert all(2.0 <= t <= 6.0 for t in sample_times(2.0, 6.0, frames))
    assert sample_times(2.0, 6.0, 1) == (4.0,)


@pytest.mark.parametrize("start,end", [(5, 5), (6, 2), (-1, 3), (float("nan"), 3), (0, float("inf")), ("a", 3)])
def test_invalid_ranges_fail_safely(start, end):
    with pytest.raises(FrameSamplingError) as caught:
        sample_times(start, end, 3)
    assert caught.value.code == "invalid-range"


def test_missing_source_and_unavailable_ffmpeg(tmp_path, monkeypatch):
    sampler = FfmpegFrameSampler(executable="ffmpeg-stub")
    with pytest.raises(FrameSamplingError) as caught:
        sampler.sample(str(tmp_path / "missing.mp4"), 0, 4)
    assert caught.value.code == "source-unavailable"
    media = tmp_path / "a.mp4"
    media.write_bytes(b"x")
    monkeypatch.delenv("BIN_FINDER_FFMPEG", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(FrameSamplingError) as caught:
        FfmpegFrameSampler().sample(str(media), 0, 4)
    assert caught.value.code == "ffmpeg-unavailable"


def test_symlink_source_rejected_when_supported(tmp_path):
    real = tmp_path / "real.mp4"
    real.write_bytes(b"x")
    link = tmp_path / "link.mp4"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("Creating symlinks needs Windows privilege or Developer Mode")
    with pytest.raises(FrameSamplingError) as caught:
        FfmpegFrameSampler(executable="ffmpeg-stub").sample(str(link), 0, 4)
    assert caught.value.code == "source-unavailable"


def test_ffmpeg_timeout_and_bad_output_fail_safely(tmp_path, monkeypatch):
    media = tmp_path / "a.mp4"
    media.write_bytes(b"x")
    sampler = FfmpegFrameSampler(executable="ffmpeg-stub",
                                 policy=FrameSamplingPolicy(max_frame_bytes=2048))
    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(FrameSamplingError) as caught:
        sampler.sample(str(media), 0, 4)
    assert caught.value.code == "no-frames"
    for stdout in (b"x" * 4096 + b"\xff\xd8\xff", b"not-a-jpeg", b""):
        monkeypatch.setattr(subprocess, "run", lambda c, **k: subprocess.CompletedProcess(c, 0, stdout, b""))
        with pytest.raises(FrameSamplingError):
            sampler.sample(str(media), 0, 4)  # oversized / non-JPEG / empty


def test_sampler_command_is_bounded_and_shell_free(tmp_path, monkeypatch):
    media = tmp_path / "a.mp4"
    media.write_bytes(b"x")
    commands = []
    def run(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, JPEG, b"")
    monkeypatch.setattr(subprocess, "run", run)
    frames = FfmpegFrameSampler(executable="ffmpeg-stub").sample(str(media), 1.0, 5.0)
    assert len(frames) == 3 and len(commands) == 3
    for command, kwargs in commands:
        assert kwargs.get("shell", False) is False and kwargs["timeout"] == 30.0
        assert "-frames:v" in command and command[command.index("-frames:v") + 1] == "1"
        assert any("min(960,iw)" in part for part in command)
        assert "-fs" in command and command[-1] == "-"
        assert str(media) in command
    for bad in (dict(frames=0), dict(frames=7), dict(max_width=1), dict(timeout=0)):
        with pytest.raises(ValueError):
            FfmpegFrameSampler(executable="x", policy=FrameSamplingPolicy(**bad))


FFMPEG = FfmpegFrameSampler().executable


@pytest.mark.skipif(not FFMPEG or not shutil.which(FFMPEG), reason="FFmpeg unavailable")
def test_real_ffmpeg_sampling_yields_bounded_jpegs(tmp_path):
    media = tmp_path / "wide.mp4"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=s=1920x1080:r=10", "-t", "4", "-pix_fmt", "yuv420p", str(media)],
                   check=True, timeout=60)
    frames = FfmpegFrameSampler().sample(str(media), 0.5, 3.5)
    assert len(frames) == 3 and all(f[:3] == b"\xff\xd8\xff" and len(f) <= 2_000_000 for f in frames)
    # SOF0/SOF2 header carries the real (downscaled) dimensions.
    for frame in frames:
        marker = next(i for i in range(len(frame) - 9) if frame[i] == 0xFF and frame[i + 1] in (0xC0, 0xC2))
        height, width = int.from_bytes(frame[marker + 5:marker + 7], "big"), int.from_bytes(frame[marker + 7:marker + 9], "big")
        assert width == 960 and height == 540


# ---------------------------------------------------------------- endpoint / config
@pytest.mark.parametrize("url", ["http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434",
                                 "http://localhost", "http://127.0.0.1:11434/"])
def test_loopback_endpoints_accepted(url):
    assert validate_loopback_url(url).startswith("http://")
    assert OllamaVisionVerifier(VlmConfig(url=url), FakeSampler(), FakeOpener(b"{}")).base_url


@pytest.mark.parametrize("url", ["http://example.com:11434", "http://192.168.1.5:11434",
    "https://127.0.0.1:11434", "http://0.0.0.0:11434", "http://user:pw@127.0.0.1", "http://127.0.0.1/x",
    "http://127.0.0.1?a=1", "ftp://127.0.0.1", "127.0.0.1:11434", "http://127.0.0.1.evil.com", ""])
def test_non_loopback_or_decorated_endpoints_rejected(url):
    with pytest.raises(VlmConfigError):
        validate_loopback_url(url)
    with pytest.raises(VlmConfigError):
        OllamaVisionVerifier(VlmConfig(url=url), FakeSampler(), FakeOpener(b"{}"))


def test_config_from_env_defaults_and_validation():
    config = config_from_env({})
    assert (config.mode, config.model, config.url, config.timeout, config.frames) == (
        "auto", "qwen3-vl:4b", "http://127.0.0.1:11434", 120.0, 3)
    custom = config_from_env({"BIN_FINDER_VLM_MODEL": "llava:7b", "BIN_FINDER_VLM_FRAMES_PER_UNIT": "2",
                              "BIN_FINDER_VLM_TIMEOUT_SECONDS": "30", "BIN_FINDER_VLM_MODE": "HEURISTIC"})
    assert (custom.model, custom.frames, custom.timeout, custom.mode) == ("llava:7b", 2, 30.0, "heuristic")
    for bad in ({"BIN_FINDER_VLM_MODEL": "a b;rm"}, {"BIN_FINDER_VLM_FRAMES_PER_UNIT": "99"},
                {"BIN_FINDER_VLM_TIMEOUT_SECONDS": "nan"}, {"BIN_FINDER_VLM_TIMEOUT_SECONDS": "0"},
                {"BIN_FINDER_VLM_MODE": "cloud"}, {"BIN_FINDER_OLLAMA_URL": "http://evil.example"}):
        with pytest.raises(VlmConfigError):
            config_from_env(bad)


# ---------------------------------------------------------------- request content
def test_request_is_loopback_json_with_image_evidence_only():
    opener = FakeOpener(envelope(GOOD))
    sampler = FakeSampler()
    result = verifier(opener, sampler).verify(SCENE, [unit()])[0]
    assert result is not None
    request, timeout = opener.requests[0]
    assert request.full_url == "http://127.0.0.1:11434/api/chat" and request.get_method() == "POST"
    assert timeout == 120.0 and "authorization" not in {k.lower() for k in request.headers}
    body = json.loads(request.data)
    assert body["stream"] is False and body["options"]["temperature"] == 0
    message = body["messages"][0]
    assert len(message["images"]) == 3
    assert all(base64.b64decode(image)[:3] == b"\xff\xd8\xff" for image in message["images"])
    for needle in ("Young workers", "workers", "desks", "empty", "2.0", "6.0"):
        assert needle in message["content"]
    # Visual judging only: no transcript/metadata and no host path or video container bytes.
    assert "workers at their desks" not in message["content"]
    assert "D:/media" not in request.data.decode() and b"ftyp" not in request.data
    assert len(request.data) < 1_000_000
    assert sampler.calls == [("D:/media/clip.mp4", 2.0, 6.0)]


def test_prompt_is_bounded():
    huge = replace(SCENE, english_text="x" * 5000, context=SceneContext(subject=tuple("s" * 500 for _ in range(50))))
    prompt = build_prompt(huge, unit(), 3)
    assert len(prompt) < 6000


# ---------------------------------------------------------------- strict parsing
def test_valid_json_maps_all_seven_dimensions():
    result = parse_vlm_response(json.dumps(GOOD), "u1", "ollama-vlm:m")
    assert isinstance(result, VerificationResult) and result.unit_id == "u1"
    assert result.provider == "ollama-vlm:m" and result.confidence == .85
    expected = {name: GOOD[name] for name in DIMENSIONS}
    assert result.dimensions == VerificationDimensions(**expected)
    assert result.dimensions.location_match is None and result.dimensions.context_conflict == .1
    fenced = parse_vlm_response("```json\n" + json.dumps(GOOD) + "\n```", "u1", "p")
    assert fenced.dimensions == result.dimensions
    extras = parse_vlm_response(json.dumps({**GOOD, "extra": [1, 2], "explanation": "a\x00b\n\tc" + "z" * 900}), "u1", "p")
    assert "\x00" not in extras.explanation and len(extras.explanation) <= 300


@pytest.mark.parametrize("change", [
    {"subject_match": 1.5}, {"subject_match": -0.2}, {"subject_match": 85}, {"visual_quality": "0.9"},
    {"action_match": True}, {"object_match": [0.5]}, {"confidence": None}, {"confidence": 2},
    {"confidence": "high"}])
def test_out_of_range_and_non_numeric_scores_rejected(change):
    with pytest.raises(VlmResponseError):
        parse_vlm_response(json.dumps({**GOOD, **change}), "u1", "p")


@pytest.mark.parametrize("text", ["", "   ", "not json", "{", "[1,2]", "null", '"text"', "123",
    '{"subject_match": NaN, "confidence": .5}', '{"subject_match": Infinity, "confidence": .5}',
    '{"confidence": .5}', json.dumps({k: None for k in DIMENSIONS} | {"confidence": .5}),
    "Sure! " + json.dumps(GOOD), "OVERSIZED"])
def test_malformed_or_unusable_responses_rejected(text):
    text = "x" * 2_000_000 if text == "OVERSIZED" else text
    with pytest.raises(VlmResponseError):
        parse_vlm_response(text, "u1", "p")


def test_nonfinite_values_are_never_returned():
    with pytest.raises(VlmResponseError):
        parse_vlm_response('{"subject_match": 1e999, "confidence": 0.5}', "u1", "p")


# ---------------------------------------------------------------- provider behavior
def test_primary_success_uses_real_vlm_result_and_identifies_provider():
    results = verifier(FakeOpener(envelope(GOOD))).verify(SCENE, [unit(1), unit(2)])
    assert [r.unit_id for r in results] == ["u1", "u2"]
    assert all(r.provider == "ollama-vlm:qwen3-vl:4b" for r in results)
    assert verifier(FakeOpener(envelope(GOOD)), model="llava:7b").name == "ollama-vlm:llava:7b"


def test_http_failure_stops_further_requests_and_falls_back_to_heuristic():
    opener = FakeOpener(urllib.error.URLError("refused"))
    primary = verifier(opener)
    assert primary.verify(SCENE, [unit(1), unit(2), unit(3)]) == [None, None, None]
    assert len(opener.requests) == 1  # no waiting through every unit
    provider = FallbackVerificationProvider(verifier(FakeOpener(urllib.error.URLError("x"))),
                                            HeuristicContextVerifier())
    results = provider.verify(SCENE, [unit(1), unit(2)])
    assert [r.provider for r in results] == ["heuristic-context"] * 2


def test_missing_model_and_timeout_fall_back():
    not_found = urllib.error.HTTPError("http://127.0.0.1:11434/api/chat", 404, "model not found", {}, None)
    for error in (not_found, TimeoutError("timed out"), OSError("reset")):
        provider = FallbackVerificationProvider(verifier(FakeOpener(error)), HeuristicContextVerifier())
        results = provider.verify(SCENE, [unit(1)])
        assert len(results) == 1 and results[0].provider == "heuristic-context"


def test_oversized_and_bad_envelopes_fail_per_unit():
    for body in (b"x" * 1_100_000, b"not json", json.dumps({"message": {}}).encode(),
                 json.dumps({"message": {"content": 5}}).encode()):
        assert verifier(FakeOpener(body)).verify(SCENE, [unit()]) == [None]


def test_per_unit_failure_only_falls_back_that_unit():
    opener = FakeOpener(envelope(GOOD), envelope("not json"), envelope(GOOD))
    sampler = FakeSampler(fail={4})  # 4th sample call = 4th unit
    provider = FallbackVerificationProvider(verifier(opener, sampler), HeuristicContextVerifier())
    units = [unit(i) for i in range(1, 5)]
    results = provider.verify(SCENE, units)
    assert [r.unit_id for r in results] == ["u1", "u2", "u3", "u4"]
    assert [r.provider for r in results] == [
        "ollama-vlm:qwen3-vl:4b", "heuristic-context", "ollama-vlm:qwen3-vl:4b", "heuristic-context"]


def test_composite_always_returns_one_ordered_entry_per_unit():
    class Short:
        name = "short"
        def verify(self, scene, units):
            # Shorter than the request and only the second entry is usable.
            return [None, VerificationResult("u2", "short", VerificationDimensions(subject_match=.5))]
    class Wrong(Short):
        def verify(self, scene, units):
            return [VerificationResult("zzz", "short", VerificationDimensions(subject_match=.5))] * len(units)
    class Boom(Short):
        def verify(self, scene, units):
            raise RuntimeError("boom")
    for primary in (Short(), Wrong(), Boom()):
        results = FallbackVerificationProvider(primary, HeuristicContextVerifier()).verify(
            SCENE, [unit(1), unit(2), unit(3)])
        assert [r.unit_id for r in results] == ["u1", "u2", "u3"]
    assert FallbackVerificationProvider(Short(), HeuristicContextVerifier()).verify(
        SCENE, [unit(1), unit(2), unit(3)])[1].provider == "short"
    assert FallbackVerificationProvider(Boom(), HeuristicContextVerifier()).verify(SCENE, []) == []


# ---------------------------------------------------------------- reranker integration
def ranked(i, text="workers at their desks"):
    return RankedSegment(unit(i, text=text), RetrievalScores(.5, .5, .5, None, .5 + i / 100))


def test_reranker_scoring_and_top_n_unchanged():
    class Stub:
        name = "stub"
        calls = []
        def verify(self, scene, units):
            Stub.calls.append(len(units))
            return [parse_vlm_response(json.dumps(GOOD), u.unit_id, "stub") for u in units]
    items = [ranked(i) for i in range(1, 5)]
    via_vlm = VerificationReranker(FallbackVerificationProvider(verifier(FakeOpener(envelope(GOOD))),
                                   HeuristicContextVerifier()), top_n=2).rerank(SCENE, items)
    via_stub = VerificationReranker(Stub(), top_n=2).rerank(SCENE, items)
    assert Stub.calls == [2]
    assert [(v.status, v.final_score, v.verification_score) for v in via_vlm] == \
           [(v.status, v.final_score, v.verification_score) for v in via_stub]
    assert [v.status for v in via_vlm] == ["verified", "verified", "outside-top-n", "outside-top-n"]
    assert via_vlm[0].verification.provider == "ollama-vlm:qwen3-vl:4b"


def test_f018_keyword_fallback_still_works_when_vlm_fails():
    raw = SceneRecord("s", 1, "Young workers remain at their desks late.", context=SceneContext())
    provider = FallbackVerificationProvider(verifier(FakeOpener(OSError("down"))), HeuristicContextVerifier())
    result = VerificationReranker(provider).rerank(raw, [ranked(1)])[0]
    assert result.status == "verified" and result.verification_score > 0
    assert result.verification.provider == "heuristic-context"


def test_f014_human_approval_remains_mandatory(make_item):  # noqa: F811
    scene, item = make_item()
    service = FinalSelectionService()
    option = service.options(scene, item)[0]
    assert not service.approve(scene, item, option.clip_id, [scene]).accepted
    assert service.approve(scene, item, option.clip_id, [scene], human_approved=True).accepted
    # The historical not-configured path still prepares with the heuristic, no Ollama involved.
    prepared = service.prepare(scene, replace(item, verified=(), proposals=()))
    assert service.options(scene, prepared)


# ---------------------------------------------------------------- factory / wiring
def test_factory_modes(monkeypatch):
    reranker = production_verifier({})
    assert isinstance(reranker, VerificationReranker)
    assert isinstance(reranker.provider, FallbackVerificationProvider)
    assert isinstance(reranker.provider.primary, OllamaVisionVerifier)
    assert isinstance(reranker.provider.fallback, HeuristicContextVerifier)
    assert production_verifier({"BIN_FINDER_VLM_MODE": "off"}) is None
    assert isinstance(production_verifier({"BIN_FINDER_VLM_MODE": "heuristic"}).provider, HeuristicContextVerifier)
    monkeypatch.setattr(factory_module, "OllamaVisionVerifier",
                        lambda *a, **k: pytest.fail("invalid configuration must not create a VLM client"))
    for env in ({"BIN_FINDER_OLLAMA_URL": "http://example.com:11434"}, {"BIN_FINDER_VLM_MODE": "cloud"}):
        assert isinstance(production_verifier(env).provider, HeuristicContextVerifier)


def test_building_the_verifier_does_no_io(monkeypatch):
    monkeypatch.setattr(OllamaVisionVerifier, "_chat", lambda *a: pytest.fail("network call"))
    monkeypatch.setattr(FfmpegFrameSampler, "sample", lambda *a: pytest.fail("ffmpeg call"))
    assert production_verifier({}) is not None


def test_production_workflow_service_receives_the_verifier(monkeypatch):
    from bin_finder.demo_data import demo_candidates
    from bin_finder.gui import main_window
    captured = {}
    class Captured(Exception):
        pass
    def spy(*args, **kwargs):
        captured.update(kwargs)
        raise Captured()
    monkeypatch.setattr(main_window.WorkflowService, "__init__", spy)
    monkeypatch.setattr(main_window.MainWindow, "_search_scene", lambda *a: None)
    monkeypatch.setattr(OllamaVisionVerifier, "_chat", lambda *a: pytest.fail("VLM call on GUI thread"))
    window = main_window.MainWindow()
    try:
        window.review_panel.candidate = demo_candidates("scene_001")[0]
        with pytest.raises(Captured):
            window._process_current_candidate()
        verifier_arg = captured["verifier"]
        assert isinstance(verifier_arg, VerificationReranker)
        assert isinstance(verifier_arg.provider, FallbackVerificationProvider)
    finally:
        window.close()


def test_gui_flow_usable_when_ollama_absent():
    """Real urllib against a closed loopback port: fast refusal, heuristic fallback, still verified."""
    primary = OllamaVisionVerifier(VlmConfig(url="http://127.0.0.1:9", timeout=2), FakeSampler())
    provider = FallbackVerificationProvider(primary, HeuristicContextVerifier())
    results = VerificationReranker(provider).rerank(SCENE, [ranked(1), ranked(2)])
    assert [r.status for r in results] == ["verified", "verified"]
    assert all(r.verification.provider == "heuristic-context" for r in results)


def test_runtime_dependencies_unchanged():
    root = Path(__file__).resolve().parents[1]
    assert (root / "requirements.txt").read_text(encoding="utf-8").split() == ["PyQt6>=6.7,<7"]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dependencies = ["PyQt6>=6.7,<7"]' in pyproject


def test_earlier_milestone_defaults_unchanged():
    from bin_finder.acceptance import AcceptancePolicy, production_acceptance_policy
    from bin_finder.final_export import ExportOptions
    assert AcceptancePolicy().max_duration_seconds == 180.0                       # F010
    assert production_acceptance_policy().max_duration_seconds is None             # F019
    assert ExportOptions().handoff is False                                        # F017 core
    from bin_finder.gui.panels import ExportPanel, ProjectPanel
    assert ExportPanel(ProjectPanel()).handoff_option.isChecked()                  # F020 GUI


# ---------------------------------------------------------------- live smoke guard
def test_live_smoke_requires_explicit_approval(monkeypatch, capsys):
    monkeypatch.setattr(ollama_smoke, "run_smoke", lambda: pytest.fail("unapproved live VLM run"))
    assert ollama_smoke.main([]) == 0
    assert capsys.readouterr().out.strip() == "SKIPPED_NOT_APPROVED"


def test_live_smoke_rejects_non_loopback_config_without_network(monkeypatch, capsys):
    monkeypatch.setenv("BIN_FINDER_OLLAMA_URL", "http://example.com:11434")
    monkeypatch.setattr(ollama_smoke, "OllamaVisionVerifier", lambda *a: pytest.fail("client created"))
    assert ollama_smoke.main(["--approve-live-vlm"]) == 2
    assert "invalid configuration" in capsys.readouterr().out


# ------------------------------------------------- real HTTP wire path (stdlib loopback server)
def serve(handler_factory):
    import http.server
    import threading
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler_factory)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.mark.skipif(not FFMPEG or not shutil.which(FFMPEG), reason="FFmpeg unavailable")
def test_real_urllib_and_ffmpeg_against_loopback_stub_server(tmp_path):
    import http.server
    seen = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            body = envelope(GOOD)
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    media = tmp_path / "clip.mp4"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=blue:s=640x360:r=10", "-t", "5", "-pix_fmt", "yuv420p", str(media)],
                   check=True, timeout=60)
    server = serve(Handler)
    try:
        port = server.server_address[1]
        real = OllamaVisionVerifier(VlmConfig(url=f"http://127.0.0.1:{port}", timeout=10))
        result = real.verify(SCENE, [RetrievalUnit("real", str(media), 0.5, 4.5)])[0]
        assert result is not None and result.provider == "ollama-vlm:qwen3-vl:4b"
        path, body = seen[0]
        images = body["messages"][0]["images"]
        assert path == "/api/chat" and len(images) == 3
        assert all(base64.b64decode(i)[:3] == b"\xff\xd8\xff" for i in images)
        assert media.stat().st_size not in {len(base64.b64decode(i)) for i in images}
    finally:
        server.shutdown()


def test_redirects_are_not_followed():
    import http.server
    hits = []
    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            hits.append(self.path)
            self.send_response(307)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()
        def log_message(self, *args):
            pass
    server = serve(Redirect)
    try:
        port = server.server_address[1]
        real = OllamaVisionVerifier(VlmConfig(url=f"http://127.0.0.1:{port}", timeout=5), FakeSampler())
        assert real.verify(SCENE, [unit()]) == [None]
        assert hits == ["/api/chat"]
    finally:
        server.shutdown()
