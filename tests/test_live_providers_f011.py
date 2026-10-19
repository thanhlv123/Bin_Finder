import io
import json
from urllib.error import HTTPError, URLError

import pytest

from bin_finder.models import FootageProject, SceneRecord, SelectedClipRecord
from bin_finder.acceptance import AcceptancePolicy, evaluate_project
from bin_finder.integration_adapter import build_ai_video_editor_manifest
from bin_finder.evaluation import ReviewDecision, ReviewStore
from bin_finder.providers.base import ProviderError, SearchRequest
from bin_finder.providers.http import JsonHttpClient
from bin_finder.providers.pexels import PexelsProvider
from bin_finder.providers.pixabay import PixabayProvider
from bin_finder.providers.local import LocalLibraryProvider
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.service import DiscoveryService, SearchOptions


class FakeHttp:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_json(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


PROVIDERS = [(PexelsProvider, "videos"), (PixabayProvider, "hits")]


def payload(key, **extra):
    return {key: [{"id": 7, "duration": 12, **extra}]}


@pytest.mark.parametrize("cls,key", PROVIDERS)
def test_readiness_and_missing_key(cls, key):
    http = FakeHttp({})
    assert cls("configured", http).status().configured
    provider = cls("  ", http)
    assert not provider.status().configured
    assert provider.search(SearchRequest("s", "car")).notice
    assert not http.calls


@pytest.mark.parametrize("cls,key", PROVIDERS)
def test_empty(cls, key):
    assert not cls("test", FakeHttp({key: []})).search(SearchRequest("s", "car")).candidates


@pytest.mark.parametrize("cls,key", PROVIDERS)
@pytest.mark.parametrize("bad", [None, [], {}, {"videos": {}, "hits": "oops"}])
def test_malformed(cls, key, bad):
    with pytest.raises(ProviderError):
        cls("test", FakeHttp(bad)).search(SearchRequest("s", "car"))


@pytest.mark.parametrize("cls,key", PROVIDERS)
def test_partial_fields(cls, key):
    provider = cls("test", FakeHttp({key: [None, {}, {"id": 7, "duration": "NaN",
        "user": [], "video_files": {}, "videos": [], "width": "bad"}]}))
    item, = provider.search(SearchRequest("s", "car")).candidates
    assert item.source_id == f"{provider.key}:7"
    assert item.duration == 0 and item.scene_id == "s"
    assert item.source_metadata["usage_authorization"] == "unknown"


def test_pexels_rendition_and_provenance():
    files = [{"id": 2, "link": "https://media/b", "width": 1920, "height": 1080},
             {"id": 1, "link": "https://media/a", "width": 1920, "height": 1080},
             {"width": 9000, "height": 9000},
             {"link": "https://media/unsupported", "file_type": "video/unknown"}]
    def run(values):
        return PexelsProvider("test", FakeHttp(payload("videos", video_files=values,
            url="https://pexels.com/video/7", image="https://media/thumb",
            user={"name": "Author", "id": 3}))).search(SearchRequest("s", "car")).candidates[0]
    a, b = run(files), run(list(reversed(files)))
    assert a == b and a.preview_url == "https://media/a"
    assert a.resolution == "1920x1080" and a.creator == "Author"
    assert a.source_url == "https://pexels.com/video/7"
    assert len(a.source_metadata["renditions"]) == 2


def test_pixabay_rendition_and_limit():
    videos = {"large": {"url": ""}, "tiny": {"url": "https://media/tiny"},
              "medium": {"url": "https://media/hd", "width": 1920, "height": 1080,
                         "thumbnail": "https://media/thumb"}}
    item, = PixabayProvider("test", FakeHttp(payload("hits", videos=videos,
        pageURL="https://pixabay.com/videos/7", user="Author", tags="car, city"))).search(
            SearchRequest("s", "car", limit=1)).candidates
    assert item.preview_url == "https://media/hd"
    assert item.thumbnail_url == "https://media/thumb" and item.description == "car, city"
    assert item.source_metadata["rendition"] == "medium"


@pytest.mark.parametrize("cls,key", PROVIDERS)
@pytest.mark.parametrize("failure", [401, 403, 429, 500, "network", "timeout", "encoding", "json", "shape"])
def test_http_errors_are_safe(monkeypatch, failure, cls, key):
    secret = "synthetic-private-credential"
    def response(*args, **kwargs):
        assert kwargs["timeout"] == 15
        if isinstance(failure, int):
            raise HTTPError(f"https://api/?key={secret}", failure, secret, {}, None)
        if failure == "network":
            raise URLError(secret)
        if failure == "timeout":
            raise TimeoutError(secret)
        return io.BytesIO({"encoding": b"\xff", "json": b"oops", "shape": b"[]"}[failure])
    monkeypatch.setattr("bin_finder.providers.http.urlopen", response)
    with pytest.raises(ProviderError) as exc:
        cls(secret).search(SearchRequest("s", "car"))
    assert secret not in str(exc.value)


@pytest.mark.parametrize("cls,key", PROVIDERS)
def test_provider_http_failure_isolated_with_local(tmp_path, cls, key):
    (tmp_path / "car.mp4").write_bytes(b"fixture")
    failing = cls("test", FakeHttp(ProviderError("safe failure")))
    other = PixabayProvider if cls is PexelsProvider else PexelsProvider
    other_key = "hits" if other is PixabayProvider else "videos"
    working = other("test", FakeHttp(payload(other_key)))
    service = DiscoveryService(ProviderRegistry([failing, working, LocalLibraryProvider(str(tmp_path))]))
    result = service.search_scene(SceneRecord("s", 1, "car"), SearchOptions(
        (failing.key, working.key, "local"), local_first=False))
    assert {c.provider for c in result.candidates} == {working.key, "local"}
    assert "safe failure" in result.notices


@pytest.mark.parametrize("cls,key", PROVIDERS)
def test_provenance_ranking_review_and_handoff(tmp_path, cls, key):
    provider = cls("test", FakeHttp(payload(key, url="https://pexels.com/video/7",
        pageURL="https://pixabay.com/videos/7", user={"name": "Author"} if key == "videos" else "Author")))
    scene = SceneRecord("s", 1, "car")
    item, = DiscoveryService(ProviderRegistry([provider])).search_scene(
        scene, SearchOptions((provider.key,))).candidates
    store = ReviewStore(tmp_path / "review.json")
    store.record_decision(ReviewDecision("s", item.candidate_id, "accepted",
        source_url=item.source_url, creator=item.creator, source_metadata=item.source_metadata))
    assert json.loads((tmp_path / "review.json").read_text())["decisions"][0]["source_metadata"] == item.source_metadata
    clip = SelectedClipRecord("clip", "s", 1, item.provider, item.source_id, item.title,
        str(tmp_path / "approved.mp4"), 0, 5, 5, .9, .9, .9, item.rights_status,
        source_url=item.source_url, creator=item.creator, source_metadata=item.source_metadata)
    project = FootageProject("test", tmp_path, [scene], [clip])
    manifest = build_ai_video_editor_manifest(project, evaluate_project(project, AcceptancePolicy(min_duration_seconds=0)))
    footage = manifest["scenes"][0]["footage"]
    assert footage["source_metadata"] == item.source_metadata and footage["source_url"] == item.source_url
    assert project.to_manifest()["clips"][0]["creator"] == item.creator


@pytest.mark.parametrize("cls,key", PROVIDERS)
def test_real_http_boundary_uses_video_endpoint_without_media_fetch(monkeypatch, cls, key):
    calls = []
    def response(request, *, timeout):
        calls.append(request)
        return io.BytesIO(json.dumps(payload(key)).encode())
    monkeypatch.setattr("bin_finder.providers.http.urlopen", response)
    result = cls("synthetic-key").search(SearchRequest("s", "car"))
    assert len(result.candidates) == len(calls) == 1
    assert calls[0].full_url.startswith(cls.SEARCH_URL)
    if cls is PexelsProvider:
        assert calls[0].get_header("Authorization") == "synthetic-key"
    else:
        assert "key=synthetic-key" in calls[0].full_url


def test_smoke_without_credentials_never_calls_http(monkeypatch):
    from bin_finder.provider_config import ProviderConfig
    from bin_finder.provider_smoke import run
    monkeypatch.setattr(ProviderConfig, "load", lambda: ProviderConfig())
    monkeypatch.setattr(JsonHttpClient, "get_json", lambda *a, **k: pytest.fail("unexpected network"))
    assert set(run().values()) == {"SKIPPED_NO_CREDENTIAL"}
