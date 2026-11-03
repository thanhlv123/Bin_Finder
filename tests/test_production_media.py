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


@pytest.mark.parametrize("failures", [1, 3])
def test_download_retries_network_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failures: int) -> None:
    from bin_finder.production import media
    calls = []
    delays = []

    class FlakyOpener:
        def open(self, request: object, timeout: float) -> BytesIO:
            calls.append(1)
            if len(calls) <= failures:
                raise TimeoutError("private network detail")
            return BytesIO(b"complete clip")

    monkeypatch.setattr(media, "build_opener", lambda *handlers: FlakyOpener())
    monkeypatch.setattr(media, "sleep", delays.append)
    monkeypatch.setattr(media, "probe_media", lambda *values: MediaInfo(4, 1920, 1080))
    config = ProductionConfig(cache_dir=str(tmp_path))
    if failures == 3:
        with pytest.raises(ProductionError, match="Selected media download failed"):
            acquire_media(candidate(), config)
        assert delays == [2, 5]
        assert not list(tmp_path.rglob("*.part"))
    else:
        assert acquire_media(candidate(), config).read_bytes() == b"complete clip"
        assert delays == [2]
    assert len(calls) == min(failures + 1, 3)


@pytest.mark.parametrize("has_alternative", [True, False])
def test_three_cues_exhausted_source(tmp_path: Path, has_alternative: bool) -> None:
    from types import SimpleNamespace
    from bin_finder.production.__main__ import choose_available_media
    from bin_finder.production.media import plan_clip
    from bin_finder.production.timeline import Shot
    original = candidate()
    alternative = deepcopy(original)
    alternative["source_id"] = "next-source"
    alternative["license"]["source_id"] = "next-source"
    positions = {}
    paths = {}
    shots = []
    for index in range(3):
        cue_id = f"cue-{index}"
        shot = Shot(cue_id, "forest", index * 3, (index + 1) * 3,
                    original["source_id"], original["provider"], "", "selected", {})
        ranked = [{"source_id": original["source_id"]}]
        if has_alternative:
            ranked.append({"source_id": alternative["source_id"]})
        entry = {"candidate": original, "cue": {"ranked": ranked}}
        footage = SimpleNamespace(cues=[{"cue_id": cue_id, "candidates": [original, alternative]}],
                                  youtube_usage_path="")
        chosen, info = choose_available_media(
            shot, entry, footage, ProductionConfig(), paths, positions,
            lambda record, config: tmp_path / record["source_id"].replace(":", "_"),
            lambda *values: MediaInfo(4, 1920, 1080), [],
        )
        key = (shot.provider, shot.source_id)
        plan_clip(shot, chosen, info, 3, positions.get(key, 0))
        positions[key] = shot.clip_out
        shots.append(shot)
    if has_alternative:
        assert shots[1].source_id == "next-source"
        assert shots[1].license["source_id"] == "next-source"
        assert "Source exhausted; used next ranked candidate" in shots[1].notes
    else:
        assert "Source reused from start" in shots[1].notes
        assert shots[1].clip_in == 0
        assert shots[2].clip_in >= shots[1].clip_out
