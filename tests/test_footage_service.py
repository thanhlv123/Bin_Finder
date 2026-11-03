from dataclasses import replace
import json

from bin_finder.brief import BriefPlan, Cue, ShotBrief
from bin_finder.footage import FootageConfig, FootagePlan, search_footage
from bin_finder.footage.credits import LicenseInfo, render_credits
from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderError, ProviderStatus, ProviderSearchResult
from bin_finder.providers.registry import ProviderRegistry


def make_plan():
    cues = [Cue(f"cue-{i}", "", f"Forest {i}", 2, 2) for i in range(3)]
    briefs = [ShotBrief(c.cue_id, "forest", "", "", "", "", "", [], [],
                       {"pexels": ["forest", "forest"]}, "heuristic", "") for c in cues]
    return BriefPlan(cues, briefs, "heuristic", 0, "script-hash")


class FakeProvider:
    def __init__(self, key, fail=False, configured=True):
        self.key, self.fail, self.configured = key, fail, configured
        self.calls = []

    def status(self):
        return ProviderStatus(self.key, self.key, self.configured)

    def search(self, request):
        self.calls.append(request)
        if self.fail:
            raise ProviderError("fake-secret must never leak")
        candidate = CandidateRecord(f"{request.scene_id}:{self.key}:1", request.scene_id,
            self.key, f"{self.key}:1", "Forest", 10, 0, resolution="1920x1080")
        return ProviderSearchResult(self.key, [candidate, candidate])


def test_cache_deduplication_roundtrip_and_youtube_switch():
    pexels, youtube = FakeProvider("pexels"), FakeProvider("youtube")
    registry = ProviderRegistry([pexels, youtube])
    config = FootageConfig(sources=["pexels", "youtube"])
    result = search_footage(make_plan(), registry, config)
    assert not youtube.calls and len(pexels.calls) == 1
    assert result.candidates_per_source == {"pexels": 3}
    assert FootagePlan.from_dict(json.loads(json.dumps(result.to_dict()))) == result
    assert len(result.brief_sha256) == 64 and result.script_sha256 == "script-hash"
    for cue in result.cues:
        assert len(cue["candidates"]) == 1
        assert cue["candidates"][0]["scene_id"] == cue["cue_id"]
    result = search_footage(make_plan(), registry, replace(config, youtube_enabled=True))
    assert len(youtube.calls) == 1
    for cue in result.cues:
        reference = cue["candidates"][1]
        assert reference["reference_only"] and not reference["license"]["usable_in_video"]


def test_errors_exclusion_and_no_secret():
    registry = ProviderRegistry([FakeProvider("pexels"), FakeProvider("coverr", fail=True),
                                 FakeProvider("unknown"), FakeProvider("pixabay", configured=False)])
    config = FootageConfig(sources=["coverr", "pexels", "unknown", "pixabay"])
    result = search_footage(make_plan(), registry, config)
    assert all(c["errors"] and len(c["candidates"]) == 1 for c in result.cues)
    credits = render_credits(LicenseInfo(**c["license"]) for cue in result.cues for c in cue["candidates"])
    assert "fake-secret" not in json.dumps(result.to_dict()) + credits
    assert all(error["source"] == "coverr" for cue in result.cues for error in cue["errors"])


def test_limits_and_dimensions():
    registry = ProviderRegistry([FakeProvider("pexels"), FakeProvider("coverr")])
    result = search_footage(make_plan(), registry, FootageConfig(max_candidates_per_cue=1))
    assert all(len(c["candidates"]) == 1 for c in result.cues)
    result = search_footage(make_plan(), registry, FootageConfig(min_width=4000))
    assert all(not c["candidates"] for c in result.cues)


def test_project_config_and_env(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/footage.local.json").write_text(json.dumps({"youtube_enabled": True, "per_query_limit": 3}))
    assert FootageConfig.load(tmp_path).youtube_enabled
    monkeypatch.setenv("BIN_FINDER_FOOTAGE_YOUTUBE_ENABLED", "false")
    monkeypatch.setenv("BIN_FINDER_FOOTAGE_SOURCES", "coverr,commons")
    config = FootageConfig.load(tmp_path)
    assert not config.youtube_enabled and config.per_query_limit == 3
    assert config.sources == ["coverr", "commons"]


def test_coverr_provider_config(tmp_path, monkeypatch):
    from bin_finder.provider_config import ProviderConfig
    monkeypatch.setenv("BIN_FINDER_COVERR_API_KEY", "fake-secret")
    config = ProviderConfig.load(tmp_path)
    assert config.coverr_api_key == "fake-secret" and "fake-secret" not in repr(config)
    registry = ProviderRegistry.from_config(config)
    assert registry.get("commons").status().configured
    assert registry.get("coverr").status().configured
