import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bin_finder.acquisition import (
    AcquisitionCancelled, AcquisitionError, AcquisitionRequest, AcquisitionService,
    verified_candidate_path,
)
from bin_finder.acquisition.service import cache_key
from bin_finder.evaluation import ReviewDecision, ReviewStore
from bin_finder.models import CandidateRecord, FootageProject, SceneRecord, SelectedClipRecord


MEDIA = b'\x00\x00\x00\x18ftypmp42' + b'fixture' * 100000


class Response(io.BytesIO):
    def __init__(self, data=MEDIA, *, length=None, content_type="video/mp4", status=200):
        super().__init__(data)
        self.headers = {"Content-Type": content_type}
        if length is not False:
            self.headers["Content-Length"] = str(len(data) if length is None else length)
        self.status = status
        self.read_sizes = []

    def read(self, size=-1):
        assert 0 < size <= 256 * 1024
        self.read_sizes.append(size)
        return super().read(size)


class Transport:
    def __init__(self, response=None, error=None):
        self.response = response or Response()
        self.error = error
        self.calls = 0

    def open(self, url, timeout):
        self.calls += 1
        assert timeout <= 60
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def candidate():
    return CandidateRecord("c", "s", "pexels", "pexels:7", "ocean", 6, .8,
        preview_url="https://media.example/7.mp4?token=private-value",
        source_url="https://pexels.com/video/7", creator="Author", resolution="1920x1080",
        source_metadata={"asset_id": "7", "creator_id": "3", "license_basis": "provider-defined",
                         "license_url": "https://pexels.com/license/", "usage_authorization": "unknown",
                         "Authorization": "private-value", "raw_response": {"key": "private-value"}})


def request(candidate, **kwargs):
    review = ReviewDecision(candidate.scene_id, candidate.candidate_id, "accepted",
                            provider=candidate.provider, source_id=candidate.source_id)
    return AcquisitionRequest(candidate, review, **{"user_authorized": True, **kwargs})


def service(tmp_path, transport=None, **kwargs):
    return AcquisitionService(tmp_path / "cache", transport=transport or Transport(),
                              probe=SimpleNamespace(executable=""), **kwargs)


@pytest.mark.parametrize("change", ["not_authorized", "rejected", "waitlist", "wrong_scene", "wrong_source"])
def test_authorization(tmp_path, candidate, change):
    req = request(candidate)
    if change == "not_authorized":
        req = replace(req, user_authorized=False)
    else:
        review = replace(req.review, **({"decision": change} if change in {"rejected", "waitlist"}
            else {"scene_id" if change == "wrong_scene" else "source_id": "wrong"}))
        req = replace(req, review=review)
    transport = Transport()
    with pytest.raises(AcquisitionError):
        service(tmp_path, transport).acquire(req)
    assert transport.calls == 0


@pytest.mark.parametrize("changes", [dict(preview_url=""), dict(preview_url="file:///x"),
    dict(preview_url="ftp://example/x"), dict(preview_url="https://user:secret@example/x"),
    dict(preview_url="https://example:bad/x"), dict(source_id=""), dict(source_id="pexels:"),
    dict(provider="youtube", source_id="youtube:7"), dict(provider="storyblocks")])
def test_invalid_input(tmp_path, candidate, changes):
    transport = Transport()
    with pytest.raises(AcquisitionError):
        service(tmp_path, transport).acquire(request(replace(candidate, **changes)))
    assert transport.calls == 0


def test_stream_atomic_manifest_cache_and_provenance(tmp_path, candidate, monkeypatch):
    monkeypatch.setenv("BIN_FINDER_PEXELS_API_KEY", "private-value")
    transport = Transport()
    svc = service(tmp_path, transport)
    progress = []
    result = svc.acquire(request(candidate), progress=lambda done, total: progress.append((done, total)))
    assert result.local_path.read_bytes() == MEDIA
    assert result.size_bytes == len(MEDIA)
    assert result.sha256 == hashlib.sha256(MEDIA).hexdigest()
    assert len(transport.response.read_sizes) > 2
    assert progress[0] == (0, len(MEDIA)) and progress[-1] == (len(MEDIA), len(MEDIA))
    assert not list(svc.root.glob(".partial-*"))
    text = result.manifest_path.read_text()
    payload = json.loads(text)
    for key in ("provider", "source_id", "source_url", "creator"):
        assert payload[key] == getattr(candidate, key)
    assert payload["source_metadata"]["asset_id"] == "7"
    assert payload["source_metadata"]["license_basis"] == "provider-defined"
    assert "private-value" not in text and "Authorization" not in text and "raw_response" not in text
    assert payload["usage_authorization"] == "user_authorized_acquisition"
    assert candidate.source_metadata["usage_authorization"] == "unknown"
    assert result.candidate.provider == candidate.provider
    assert result.candidate.source_id == candidate.source_id
    assert verified_candidate_path(result.candidate) == result.local_path
    hit = svc.acquire(request(candidate))
    assert hit.cache_hit and transport.calls == 1
    assert hit.local_path == result.local_path
    # Authorization is checked even for a cache hit.
    with pytest.raises(AcquisitionError):
        svc.acquire(request(candidate, user_authorized=False))


@pytest.mark.parametrize("damage", ["media", "manifest", "size", "path", "checksum", "authorization"])
def test_corrupted_cache_is_not_trusted(tmp_path, candidate, damage):
    transport = Transport()
    svc = service(tmp_path, transport)
    result = svc.acquire(request(candidate))
    if damage == "media":
        result.local_path.write_bytes(b"corrupted")
    elif damage == "manifest":
        result.manifest_path.write_text("invalid")
    else:
        data = json.loads(result.manifest_path.read_text())
        key = {"size": "size_bytes", "path": "local_path", "checksum": "sha256",
               "authorization": "usage_authorization"}[damage]
        data[key] = "wrong"
        result.manifest_path.write_text(json.dumps(data))
    assert verified_candidate_path(result.candidate) is None
    with pytest.raises(AcquisitionError):
        svc.acquire(request(candidate))
    assert transport.calls == 1


def test_unrelated_file_not_overwritten(tmp_path, candidate):
    svc = service(tmp_path)
    svc.root.mkdir()
    path = svc.root / cache_key(candidate)
    path.write_bytes(b"unrelated")
    with pytest.raises(AcquisitionError):
        svc.acquire(request(candidate))
    assert path.read_bytes() == b"unrelated"


@pytest.mark.parametrize("transport,limit", [
    (Transport(error=TimeoutError("private-value")), 1000000),
    (Transport(error=ConnectionError("private-value")), 1000000),
    (Transport(Response(status=403)), 1000000), (Transport(Response(status=500)), 1000000),
    (Transport(Response(length=len(MEDIA) + 1)), 1000000),
    (Transport(Response()), 100), (Transport(Response(length=False)), 100),
    (Transport(Response(b"html", content_type="text/html")), 1000000),
    (Transport(Response(b"html")), 1000000), (Transport(Response(b"")), 1000000),
])
def test_failures_leave_no_published_asset(tmp_path, candidate, transport, limit):
    svc = service(tmp_path, transport, max_bytes=limit)
    with pytest.raises(AcquisitionError) as error:
        svc.acquire(request(candidate))
    assert "private-value" not in str(error.value)
    assert not list(svc.root.iterdir())


def test_mid_stream_failure(tmp_path, candidate):
    response = Response()
    original = response.read
    def read(size):
        if response.tell():
            raise TimeoutError("https://private?key=private-value")
        return original(size)
    response.read = read
    svc = service(tmp_path, Transport(response))
    with pytest.raises(AcquisitionError) as error:
        svc.acquire(request(candidate))
    assert "private-value" not in str(error.value)
    assert not list(svc.root.iterdir())


def test_cancel_and_unknown_length(tmp_path, candidate):
    progress = []
    svc = service(tmp_path, Transport(Response(length=False)))
    with pytest.raises(AcquisitionCancelled):
        svc.acquire(request(candidate), progress=lambda n, total: progress.append((n, total)),
                    cancelled=lambda: len(progress) > 1)
    assert all(total is None for n, total in progress)
    assert not list(svc.root.iterdir())


def test_disk_failure_isolated(tmp_path, candidate, monkeypatch):
    svc = service(tmp_path)
    original = Path.open
    def failing(path, mode="r", *args, **kwargs):
        if mode == "xb":
            raise OSError("private-value")
        return original(path, mode, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", failing)
        with pytest.raises(AcquisitionError):
            svc.acquire(request(candidate))
    assert not list(svc.root.iterdir())
    assert service(tmp_path).acquire(request(candidate)).local_path.is_file()


def test_probe_rejects_invalid_video(tmp_path, candidate):
    probe = SimpleNamespace(probe=lambda path: SimpleNamespace(duration=0, width=0, height=0))
    svc = AcquisitionService(tmp_path / "cache", transport=Transport(), probe=probe)
    with pytest.raises(AcquisitionError):
        svc.acquire(request(candidate))
    assert not list(svc.root.iterdir())


def test_downstream_analysis_review_and_readiness(tmp_path, candidate):
    from bin_finder.analysis.service import CandidateAnalysisService
    from bin_finder.acceptance import evaluate_project
    from bin_finder.integration_adapter import build_ai_video_editor_manifest
    store = ReviewStore(tmp_path / "review.json")
    store.record_decision(request(candidate).review)
    svc = service(tmp_path)
    result = svc.acquire(AcquisitionRequest(candidate, store.decisions()[0], True))
    analysis = CandidateAnalysisService.__new__(CandidateAnalysisService)
    paths = []
    analysis.analyze_path = lambda path, **kwargs: paths.append(path) or "analyzed"
    assert analysis.analyze_candidate(candidate) is None
    assert analysis.analyze_candidate(result.candidate) == "analyzed"
    assert paths == [result.local_path]
    assert store.decisions()[0].decision == "accepted"
    project = FootageProject("p", tmp_path, [SceneRecord("s", 1, "ocean")])
    assert not evaluate_project(project).ready
    assert build_ai_video_editor_manifest(project, evaluate_project(project))["scenes"][0]["footage"] is None
    clip = SelectedClipRecord("clip", "s", 1, candidate.provider, candidate.source_id, candidate.title,
        str(result.local_path), 0, 5, 5, .9, .9, .9, candidate.rights_status,
        source_url=candidate.source_url, creator=candidate.creator, source_metadata=candidate.source_metadata)
    project.selected_clips.append(clip)
    assert build_ai_video_editor_manifest(project, evaluate_project(project))["scenes"][0]["footage"]["source_id"] == candidate.source_id


def test_pixabay_uses_same_authorization_and_cache_contract(tmp_path, candidate):
    candidate = replace(candidate, provider="pixabay", source_id="pixabay:7")
    result = service(tmp_path).acquire(request(candidate))
    assert verified_candidate_path(result.candidate) == result.local_path


def test_smoke_refuses_unapproved_and_skips_no_credentials(monkeypatch):
    from bin_finder.acquisition_smoke import run
    from bin_finder.provider_config import ProviderConfig
    monkeypatch.setattr(ProviderConfig, "load", lambda: ProviderConfig())
    assert set(run().values()) == {"SKIPPED_NOT_APPROVED"}
    assert set(run(approve_test_download=True).values()) == {"SKIPPED_NO_CREDENTIAL"}


def test_redirect_scheme_validation():
    from bin_finder.acquisition.transport import SafeRedirect
    from urllib.request import Request
    with pytest.raises(ValueError):
        SafeRedirect().redirect_request(Request("https://example/x"), None, 302, "", {}, "file:///secret")


def test_production_transport_does_not_forward_api_headers(monkeypatch):
    from bin_finder.acquisition.transport import StreamingTransport
    calls = []
    def opened(req, *, timeout):
        calls.append(req)
        return Response()
    monkeypatch.setattr("bin_finder.acquisition.transport.build_opener",
                        lambda *args: SimpleNamespace(open=opened))
    with StreamingTransport().open("https://example/media.mp4", 15) as response:
        assert response.status == 200
    assert len(calls) == 1
    assert calls[0].get_header("Authorization") is None
    assert set(dict(calls[0].header_items())) == {"User-agent", "Accept-encoding"}


def test_atomic_publication_exposes_media_and_manifest_together(tmp_path, candidate, monkeypatch):
    original = Path.rename
    observed = []
    def rename(source, destination):
        assert not destination.exists()
        assert sorted(p.name for p in source.iterdir()) == ["manifest.json", "media.mp4"]
        payload = json.loads((source / "manifest.json").read_text())
        assert payload["sha256"] == hashlib.sha256((source / "media.mp4").read_bytes()).hexdigest()
        observed.append(destination)
        return original(source, destination)
    monkeypatch.setattr(Path, "rename", rename)
    result = service(tmp_path).acquire(request(candidate))
    assert observed == [result.local_path.parent]


@pytest.mark.parametrize("failure", ["manifest", "publish", "deadline"])
def test_late_failure_cleans_staging(tmp_path, candidate, monkeypatch, failure):
    svc = service(tmp_path)
    if failure == "manifest":
        original = Path.write_text
        def write(path, *args, **kwargs):
            if path.name == "manifest.tmp":
                raise OSError("private-value")
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, "write_text", write)
    elif failure == "publish":
        def rename(*args):
            raise OSError("private-value")
        monkeypatch.setattr(Path, "rename", rename)
    else:
        ticks = iter([0, 301])
        monkeypatch.setattr("bin_finder.acquisition.service.time.monotonic", lambda: next(ticks))
    with pytest.raises(AcquisitionError) as error:
        svc.acquire(request(candidate))
    assert "private-value" not in str(error.value)
    assert not list(svc.root.iterdir())


def test_unknown_length_success(tmp_path, candidate):
    result = service(tmp_path, Transport(Response(length=False))).acquire(request(candidate))
    assert verified_candidate_path(result.candidate) == result.local_path
