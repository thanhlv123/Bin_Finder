import copy
import json
from pathlib import Path

import pytest

from bin_finder.providers.base import ProviderError, SearchRequest
from bin_finder.providers.commons import CommonsProvider, CommonsHttp, NoRedirect
from bin_finder.providers.coverr import CoverrProvider
from bin_finder.providers.pexels import PexelsProvider
from bin_finder.providers.pixabay import PixabayProvider
from bin_finder.providers.youtube import YouTubeProvider

FIXTURES = Path(__file__).parent / "fixtures" / "footage"


class ReplayHttp:
    def __init__(self, *names):
        self.payloads = [json.loads((FIXTURES / (name + ".json")).read_text()) for name in names]
        self.calls = []

    def get_json(self, base_url, **kwargs):
        self.calls.append((base_url, kwargs))
        return copy.deepcopy(self.payloads.pop(0))


@pytest.mark.parametrize("provider,names,source,rights", [
    (PexelsProvider, ["pexels_search"], "pexels:11", "pexels_license"),
    (PixabayProvider, ["pixabay_search"], "pixabay:22", "pixabay_content_license"),
    (CoverrProvider, ["coverr_search"], "coverr:forest-33", "coverr_license"),
    (YouTubeProvider, ["youtube_search", "youtube_videos"], "youtube:abc123", "creative_commons"),
])
def test_provider_replay(provider, names, source, rights):
    http = ReplayHttp(*names)
    result = provider("fake-secret", http).search(SearchRequest("cue", "forest"))
    c = result.candidates[0]
    assert c.source_id == source and c.creator == "Jane Doe"
    assert c.duration > 0 and c.resolution and c.title and c.source_url.startswith("https://")
    assert c.rights_status == rights
    assert "fake-secret" not in str(c)
    if provider is CoverrProvider:
        base, kwargs = http.calls[0]
        assert kwargs["headers"]["Authorization"] == "Bearer fake-secret"
        assert "fake-secret" not in base + str(kwargs["params"])
        assert kwargs["params"]["page_size"] <= 50
        assert len(result.candidates) == 2


@pytest.mark.parametrize("provider", [PexelsProvider, PixabayProvider, CoverrProvider, YouTubeProvider])
def test_missing_key_no_http(provider):
    http = ReplayHttp()
    instance = provider("", http)
    assert not instance.status().configured
    assert instance.search(SearchRequest("cue", "forest")).notice
    assert not http.calls


def test_commons_replay_security_and_budget():
    http = ReplayHttp("commons_search")
    payload = http.payloads[0]
    rogue = copy.deepcopy(payload["query"]["pages"][0])
    rogue["imageinfo"][0]["url"] = "https://upload.wikimedia.org.evil.invalid/video.webm"
    payload["query"]["pages"].append(rogue)
    provider = CommonsProvider(http, max_requests=1)
    assert provider.status().configured
    result = provider.search(SearchRequest("cue", "forest"))
    assert len(result.candidates) == 2
    c = result.candidates[0]
    assert c.source_id == "commons:1" and c.creator == "Jane Doe"
    assert c.rights_status == "cc-by-sa-4.0" and c.resolution == "1920x1080" and c.duration == 12
    assert c.source_metadata["file_title"] == c.title
    params = http.calls[0][1]["params"]
    assert params["gsrnamespace"] == 6 and params["gsrsearch"].endswith("filetype:video")
    with pytest.raises(ProviderError):
        provider.search(SearchRequest("cue", "forest"))
    with pytest.raises(ProviderError):
        NoRedirect().redirect_request(None)


def test_commons_http_bounded(monkeypatch):
    import bin_finder.providers.commons as module
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            assert size == 2_000_001
            return b"x" * size
    class Opener:
        def open(self, *args, **kwargs): return Response()
    monkeypatch.setattr(module, "build_opener", lambda *args: Opener())
    with pytest.raises(ProviderError, match="too large"):
        CommonsHttp().get_json(CommonsProvider.API, params={})


def test_commons_recorded_replay():
    from bin_finder.footage.credits import license_for
    http = ReplayHttp("commons_search_recorded")
    result = CommonsProvider(http).search(SearchRequest("cue", "kidney"))
    assert len(result.candidates) == 4
    assert http.calls[0][1]["params"]["gsrsearch"] == "kidney filetype:video"
    assert [c.rights_status for c in result.candidates] == [
        "cc-by-sa-4.0", "cc-by-sa-4.0", "cc-by-4.0", "public-domain"]
    for c in result.candidates:
        assert "?" not in c.preview_url and "utm_" not in c.preview_url
        info = license_for(c)
        assert info.usable_in_video
        assert info.license_name == c.source_metadata["license"]
        assert info.attribution_required is (c.rights_status != "public-domain")


@pytest.mark.parametrize("query", ["token=x", "utm_source=a&utm_source=b",
    "utm_source=" + "x" * 101, "utm_source=a&token=x"])
def test_commons_rejects_unsafe_query(query):
    http = ReplayHttp("commons_search")
    for page in http.payloads[0]["query"]["pages"]:
        page["imageinfo"][0]["url"] = "https://upload.wikimedia.org/video.webm?" + query
    assert not CommonsProvider(http).search(SearchRequest("cue", "forest")).candidates


def test_commons_request_budget_limits():
    assert CommonsProvider(ReplayHttp()).remaining == 1000
    assert CommonsProvider(ReplayHttp(), max_requests=5000).remaining == 5000
    for budget in (0, 5001, True, 1.5):
        with pytest.raises(ValueError, match="invalid request budget"):
            CommonsProvider(ReplayHttp(), max_requests=budget)


@pytest.mark.parametrize("key,detail", [("", "Thiếu BIN_FINDER_COVERR_API_KEY"), ("fake-secret", "Sẵn sàng")])
def test_coverr_status_detail(key, detail):
    assert CoverrProvider(key, ReplayHttp()).status().detail == detail
