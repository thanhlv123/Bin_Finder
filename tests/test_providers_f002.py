import hashlib
import hmac
from pathlib import Path

from bin_finder.providers.base import SearchRequest
from bin_finder.providers.local import LocalLibraryProvider
from bin_finder.providers.pexels import PexelsProvider
from bin_finder.providers.pixabay import PixabayProvider
from bin_finder.providers.storyblocks import StoryblocksProvider
from bin_finder.providers.youtube import YouTubeProvider, parse_youtube_duration


class FakeHttp:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get_json(self, base_url, *, params=None, headers=None, timeout=20.0, provider_name="provider"):
        self.calls.append((base_url, params or {}, headers or {}, provider_name))
        return self.payloads.pop(0)


def test_youtube_duration_parser():
    assert parse_youtube_duration("PT1H2M3S") == 3723.0
    assert parse_youtube_duration("PT47S") == 47.0
    assert parse_youtube_duration("bad") == 0.0


def test_youtube_provider_normalizes_search_and_detail_results():
    http = FakeHttp([
        {"items": [{"id": {"videoId": "abc123"}}]},
        {"items": [{
            "id": "abc123",
            "snippet": {
                "title": "Havana mechanic",
                "description": "Classic car repair in Cuba",
                "channelTitle": "Creator",
                "publishedAt": "2026-01-01T00:00:00Z",
                "thumbnails": {"high": {"url": "https://thumb"}},
            },
            "contentDetails": {"duration": "PT5M2S", "definition": "hd"},
            "status": {"license": "creativeCommon"},
        }]},
    ])
    provider = YouTubeProvider("secret-key", http=http)
    result = provider.search(SearchRequest("scene_001", "Havana mechanic", creative_commons_only=True))
    assert len(result.candidates) == 1
    item = result.candidates[0]
    assert item.source_id == "youtube:abc123"
    assert item.duration == 302.0
    assert item.rights_status == "creative_commons"
    assert item.thumbnail_url == "https://thumb"
    assert http.calls[0][1]["videoLicense"] == "creativeCommon"


def test_pexels_provider_normalizes_best_file():
    http = FakeHttp([{"videos": [{
        "id": 7,
        "duration": 12,
        "url": "https://www.pexels.com/video/havana-classic-car-7/",
        "image": "https://image",
        "user": {"name": "Pexels User"},
        "video_files": [
            {"width": 640, "height": 360, "link": "https://small"},
            {"width": 1920, "height": 1080, "link": "https://hd"},
        ],
    }]}])
    provider = PexelsProvider("pexels-key", http=http)
    result = provider.search(SearchRequest("scene_001", "Havana car", orientation="landscape"))
    item = result.candidates[0]
    assert item.provider == "pexels"
    assert item.resolution == "1920x1080"
    assert item.preview_url == "https://hd"
    assert item.thumbnail_url == "https://image"
    assert http.calls[0][2]["Authorization"] == "pexels-key"


def test_pixabay_provider_normalizes_video_rendition():
    http = FakeHttp([{"hits": [{
        "id": 9,
        "duration": 18,
        "tags": "cuba, havana, street",
        "pageURL": "https://pixabay.com/videos/9",
        "user": "PixUser",
        "videos": {"large": {"url": "https://large", "width": 1920, "height": 1080, "thumbnail": "https://thumb"}},
    }]}])
    provider = PixabayProvider("pix-key", http=http)
    result = provider.search(SearchRequest("scene_001", "Havana"))
    item = result.candidates[0]
    assert item.source_id == "pixabay:9"
    assert item.preview_url == "https://large"
    assert item.thumbnail_url == "https://thumb"
    assert item.rights_status == "pixabay_content_license"


def test_storyblocks_auth_is_deterministic_and_search_normalizes():
    http = FakeHttp([{"results": [{
        "id": "sb42",
        "title": "Mechanic and classic car",
        "duration": 6,
        "thumbnail_url": "https://sb-thumb",
        "preview_urls": {"_720p": "https://sb-preview"},
        "isEditorial": False,
        "maxResolution": "4K",
        "description": "repairing a classic car",
    }]}])
    provider = StoryblocksProvider("public", "secret", "project", "user", http=http, clock=lambda: 1000.0)
    result = provider.search(SearchRequest("scene_001", "classic car"))
    expected_expires = 4600
    expected = hmac.new(
        f"secret{expected_expires}".encode(),
        b"/api/v2/videos/search",
        hashlib.sha256,
    ).hexdigest()
    assert http.calls[0][1]["HMAC"] == expected
    assert http.calls[0][1]["EXPIRES"] == str(expected_expires)
    assert result.candidates[0].preview_url == "https://sb-preview"
    assert result.candidates[0].rights_status == "storyblocks_license_required"


def test_local_provider_finds_filename_and_does_not_require_network(tmp_path: Path):
    (tmp_path / "havana classic car.mp4").write_bytes(b"")
    (tmp_path / "unrelated.mov").write_bytes(b"")
    provider = LocalLibraryProvider(str(tmp_path))
    result = provider.search(SearchRequest("scene_001", "havana classic"))
    assert len(result.candidates) == 1
    assert result.candidates[0].title == "havana classic car"
    assert result.candidates[0].preview_url.endswith("havana classic car.mp4")
