"""Downloader boundaries use in-memory responses only."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from bin_finder.production import ProductionError
from bin_finder.production.config import ProductionConfig
from bin_finder.production.media import MediaInfo, acquire_media
from bin_finder.production.tts import NoRedirect

FIXTURES = Path(__file__).parent / "fixtures/production"


def candidate():
    return json.loads((FIXTURES / "footage.json").read_text())["cues"][0]["candidates"][0]


def test_redirect_is_disabled():
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example") is None


@pytest.mark.parametrize("link", ["http://example.com/video", "file:///tmp/video", "https://user:pass@example.com/video"])
def test_media_requires_https_without_credentials(tmp_path, link):
    record = candidate()
    record["preview_url"] = link
    with pytest.raises(ProductionError, match="HTTPS"):
        acquire_media(record, ProductionConfig(cache_dir=str(tmp_path)))


def test_download_cache_and_byte_limit(tmp_path, monkeypatch):
    from bin_finder.production import media
    calls = []

    class OfflineOpener:
        def open(self, request, timeout):
            calls.append(1)
            return BytesIO(b"fake media bytes")

    monkeypatch.setattr(media, "build_opener", lambda *handlers: OfflineOpener())
    monkeypatch.setattr(media, "probe_media", lambda *values: MediaInfo(6, 1920, 1080))
    config = ProductionConfig(cache_dir=str(tmp_path))
    path = acquire_media(candidate(), config)
    assert path.read_bytes() == b"fake media bytes"
    assert acquire_media(candidate(), config) == path
    assert len(calls) == 1
    path.write_bytes(b"corrupt")
    monkeypatch.setattr(media, "MAX_MEDIA_BYTES", 2)
    with pytest.raises(ProductionError, match="size limit"):
        acquire_media(candidate(), config)
    assert not list(tmp_path.rglob("*.part"))


def test_redirect_error_does_not_expose_signed_query(tmp_path, monkeypatch):
    from bin_finder.production import media

    class OfflineOpener:
        def open(self, request, timeout):
            raise HTTPError("https://example.com?token=private", 302, "redirect", {}, None)

    monkeypatch.setattr(media, "build_opener", lambda *handlers: OfflineOpener())
    with pytest.raises(ProductionError, match="no redirects") as failure:
        acquire_media(candidate(), ProductionConfig(cache_dir=str(tmp_path)))
    assert "private" not in str(failure.value)


def test_unusable_rejected_before_download(tmp_path, monkeypatch):
    from bin_finder.production import media

    def forbidden(*values):
        raise AssertionError("Download attempted")

    monkeypatch.setattr(media, "build_opener", forbidden)
    record = candidate()
    record["reference_only"] = True
    with pytest.raises(ProductionError, match="not eligible"):
        acquire_media(record, ProductionConfig(cache_dir=str(tmp_path)))
