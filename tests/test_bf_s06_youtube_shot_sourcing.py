"""BF-S06: YouTube metadata search AND independent local-source cutting tests."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bin_finder.clips.models import ExtractionResult
from bin_finder.models import CandidateRecord
from bin_finder.providers.youtube import YouTubeProvider
from bin_finder.search.authorized_local_cut import (
    AuthorizedCutRequest, AuthorizedLocalCutError, check_cut_request,
    export_authorized_local_cut,
)
from bin_finder.search.editorial_local_smoke import selected_excerpt
from bin_finder.search.editorial_local_model import parse_local_editorial_reply
from bin_finder.search.youtube_shot_discovery import (
    YouTubeShotDiscoveryError, discover_youtube_for_shot,
)
from bin_finder.search.youtube_shot_smoke import main


VIDEO_ID = "AbCdefG1234"


class FakeYouTubeHttp:
    def __init__(self):
        self.calls = []

    def get_json(self, base_url, *, params=None, headers=None,
                 timeout=20.0, provider_name="provider"):
        self.calls.append((base_url, params))
        if base_url.endswith("/search"):
            return {"items": [{"id": {"videoId": VIDEO_ID}}]}
        return {"items": [{
            "id": VIDEO_ID,
            "snippet": {
                "title": "French Alps winter blue piste",
                "description": "Skier on gentle slope",
                "channelTitle": "Uploader",
                "thumbnails": {"high": {"url": "https://example.com/thumb.jpg"}},
            },
            "contentDetails": {"duration": "PT47S", "definition": "hd"},
            "status": {"license": "creativeCommon"},
        }]}


def shot():
    scenes, base = selected_excerpt(2)
    row = {
        "shot_id": "SHOT_001", "slot_id": "slot2", "beat_id": "beat2",
        "scene_ids": ["scene_002"],
        "source_anchor": scenes[0].english_text,
        "visual_brief": "Savoie blue piste scenery",
        "asset_evidence_type": "location_context",
        "media_type": "video", "target_duration_seconds": 3,
        "visual_tone": "neutral", "must_show": ["ski resort"],
        "must_not_show": ["fake original accident footage", "unlabeled reenactment"],
        "search_queries": [
            {"language": "en", "text": "blue ski piste marker in alpine ski resort"},
            {"language": "fr", "text": "piste bleue station de ski Savoie"},
        ],
        "fallback_policy": "no_match",
    }
    return parse_local_editorial_reply(json.dumps({"shots": [row]}), base, scenes).shots[0]


def test_youtube_existing_provider_metadata_only_search_and_cc_flag():
    http = FakeYouTubeHttp()
    provider = YouTubeProvider("LOCAL_SECRET", http=http)
    result = discover_youtube_for_shot(shot(), provider,
                                       approve_youtube_api_search=True)
    assert result.status == "references-for-human-review"
    assert result.search_attempts == 2
    assert len(http.calls) == 4  # each search uses SEARCH + VIDEOS metadata API
    assert len(result.hits) == 1  # repeated ID deduplicated
    hit = result.hits[0]
    assert hit.watch_url == "https://www.youtube.com/watch?v=" + VIDEO_ID
    assert hit.duration_seconds == 47
    assert hit.metadata_license == "youtube-cc-label-unverified"
    assert hit.rights_status == "manual-verification-required"
    assert not hit.acquisition_allowed and not hit.clip_export_allowed
    assert result.audiovisual_downloads == 0
    assert result.user_clips_created == 0
    assert all(c[0].startswith("https://www.googleapis.com/youtube/v3/")
               for c in http.calls)
    assert all(c[1]["key"] == "LOCAL_SECRET" for c in http.calls)
    assert all(c[1].get("videoLicense") == "creativeCommon"
               for c in http.calls if c[0].endswith("/search"))


def test_no_search_without_explicit_approval():
    http = FakeYouTubeHttp()
    result = discover_youtube_for_shot(shot(), YouTubeProvider("secret", http=http))
    assert result.status == "approval-required"
    assert result.search_attempts == 0
    assert http.calls == []


def test_no_key_does_not_send_youtube_queries():
    http = FakeYouTubeHttp()
    result = discover_youtube_for_shot(
        shot(), YouTubeProvider("", http=http),
        approve_youtube_api_search=True,
    )
    assert result.status == "youtube-api-key-not-configured"
    assert result.search_attempts == 0 and http.calls == []


def test_standard_license_search_still_never_clears_rights():
    http = FakeYouTubeHttp()
    result = discover_youtube_for_shot(
        shot(), YouTubeProvider("secret", http=http),
        approve_youtube_api_search=True, creative_commons_filter=False,
        max_queries=1,
    )
    assert result.search_attempts == 1 and len(http.calls) == 2
    assert "videoLicense" not in http.calls[0][1]
    assert result.hits[0].rights_status == "manual-verification-required"
    assert result.hits[0].acquisition_allowed is False


@pytest.mark.parametrize("max_queries,max_results", [
    (0, 5), (4, 5), (1, 0), (2, 11), (True, 5),
])
def test_youtube_discovery_rejects_unbounded_calls(max_queries, max_results):
    http = FakeYouTubeHttp()
    with pytest.raises(YouTubeShotDiscoveryError, match="invalid-youtube-search-limits"):
        discover_youtube_for_shot(
            shot(), YouTubeProvider("secret", http=http),
            approve_youtube_api_search=True,
            max_queries=max_queries, max_results=max_results,
        )
    assert http.calls == []


def test_a_graphic_has_no_youtube_search_route():
    original = shot()
    graphic = replace(original, asset_evidence_type="graphic")
    with pytest.raises(YouTubeShotDiscoveryError, match="shot-not-searchable"):
        discover_youtube_for_shot(graphic, YouTubeProvider("secret"),
                                  approve_youtube_api_search=True)


def test_youtube_cli_dry_run_no_config_or_json_reads(tmp_path, capsys):
    assert main(["--plan-json", str(tmp_path / "does-not-exist.json")]) == 0
    out = capsys.readouterr().out
    assert "BFS06_STATUS: approval-required" in out
    assert "BFS06_SEARCH_ATTEMPTS: 0" in out
    assert "BFS06_AUDIOVISUAL_DOWNLOADS: 0" in out


def request(tmp_path, *, start=1, duration=3, mode="clip"):
    srcroot = tmp_path / "owned"
    dstroot = tmp_path / "clips"
    srcroot.mkdir(exist_ok=True)
    dstroot.mkdir(exist_ok=True)
    source = srcroot / "independent_master.mp4"
    source.write_bytes(b"placeholder")
    return AuthorizedCutRequest(
        source_path=str(source), source_root=str(srcroot),
        output_path=str(dstroot / ("shot.jpg" if mode == "still" else "shot.mp4")),
        output_root=str(dstroot),
        start_seconds=start, duration_seconds=duration,
        mode=mode, provenance="licensed_independent_master_copy",
    )


def test_cut_default_never_reads_media_or_launches_ffmpeg(tmp_path):
    r = request(tmp_path)
    src, dst = check_cut_request(r)
    result = export_authorized_local_cut(r)
    assert result.status == "cut-approval-required"
    assert result.output_written is False and not dst.exists()
    assert src.exists()


@pytest.mark.parametrize("duration", [0, 0.9, 7.01, float("nan"), float("inf"), -1, True])
def test_reject_invalid_clip_duration(tmp_path, duration):
    r = replace(request(tmp_path), duration_seconds=duration)
    with pytest.raises(AuthorizedLocalCutError):
        check_cut_request(r)


def test_gated_local_cut_calls_existing_ffmpeg_extractor_with_correct_interval(tmp_path):
    class FakeProbe:
        def probe(self, path):
            assert Path(path).is_file()
            return SimpleNamespace(duration=15, width=1920, height=1080)
    class FakeExtractor:
        def extract(self, proposal, output_path, overwrite=False):
            assert proposal.accepted
            assert proposal.start == 2.5
            assert proposal.end == 9.5
            assert overwrite is False
            Path(output_path).write_bytes(b"fake encoded mp4")
            return ExtractionResult(str(output_path), 16, 7)
    r = replace(request(tmp_path, start=2.5, duration=7),
                confirm_usage_rights=True, approve_local_cut=True)
    result = export_authorized_local_cut(r, ffprobe=FakeProbe(),
                                         extractor=FakeExtractor())
    assert result.status == "local-clip-created-pending-editorial-review"
    assert result.duration_seconds == 7
    assert result.output_written is True
    assert result.source_license_independently_verified is False


def test_even_with_approval_cut_cannot_exceed_local_media_duration(tmp_path):
    class FakeProbe:
        def probe(self, path):
            return SimpleNamespace(duration=5, width=1920, height=1080)
    r = replace(request(tmp_path, start=3, duration=4),
                confirm_usage_rights=True, approve_local_cut=True)
    result = export_authorized_local_cut(r, ffprobe=FakeProbe())
    assert result.status == "cut-outside-local-video"
    assert not Path(r.output_path).exists()


def test_requires_both_user_rights_confirmation_and_cut_approval(tmp_path):
    r = request(tmp_path)
    for kw in [
        {"confirm_usage_rights": True, "approve_local_cut": False},
        {"confirm_usage_rights": False, "approve_local_cut": True},
    ]:
        status = export_authorized_local_cut(replace(r, **kw)).status
        assert status == "cut-approval-required"
        assert not Path(r.output_path).exists()


def test_never_overwrite_an_existing_output(tmp_path):
    r = request(tmp_path)
    dest = Path(r.output_path)
    dest.write_bytes(b"previous")
    with pytest.raises(AuthorizedLocalCutError, match="output-already-exists"):
        export_authorized_local_cut(replace(r,
                                           confirm_usage_rights=True,
                                           approve_local_cut=True))
    assert dest.read_bytes() == b"previous"


@pytest.mark.parametrize("provenance", [
    "youtube_download", "creative_commons_youtube", "youtube_url", "", None,
])
def test_block_youtube_link_or_cc_tag_as_cut_permission(tmp_path, provenance):
    r = replace(request(tmp_path), provenance=provenance,
                confirm_usage_rights=True, approve_local_cut=True)
    with pytest.raises(AuthorizedLocalCutError, match="unsupported-media-provenance"):
        check_cut_request(r)


def test_reject_http_input_and_outside_source_root(tmp_path):
    r = request(tmp_path)
    with pytest.raises(AuthorizedLocalCutError):
        check_cut_request(replace(r, source_path="https://youtube.com/watch?v=123"))
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"x")
    with pytest.raises(AuthorizedLocalCutError, match="path-outside-local-root"):
        check_cut_request(replace(r, source_path=str(outside)))


def test_reject_symlinked_source_and_output(tmp_path):
    r = request(tmp_path)
    link = Path(r.source_root) / "linked.mp4"
    try:
        link.symlink_to(Path(r.source_path))
    except (OSError, NotImplementedError):
        pytest.skip("Windows runner lacks privilege for symlinks")
    with pytest.raises(AuthorizedLocalCutError, match="unsafe-local-link"):
        check_cut_request(replace(r, source_path=str(link)))


def test_still_window_must_be_one_to_seven_seconds(tmp_path):
    r = request(tmp_path, start=0, duration=1, mode="still")
    check_cut_request(r)
    r = replace(r, duration_seconds=7)
    check_cut_request(r)
    with pytest.raises(AuthorizedLocalCutError):
        check_cut_request(replace(r, duration_seconds=8))
