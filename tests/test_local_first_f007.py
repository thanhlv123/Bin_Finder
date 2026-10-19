from bin_finder.demo_data import demo_scenes
from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.service import DiscoveryService, SearchOptions


class CountingProvider:
    def __init__(self, key, candidate_score, title):
        self.key = key
        self.display_name = key
        self.candidate_score = candidate_score
        self.title = title
        self.calls = 0

    def status(self):
        return ProviderStatus(self.key, self.display_name, True, "ready")

    def search(self, request):
        self.calls += 1
        return ProviderSearchResult(
            self.key,
            [
                CandidateRecord(
                    candidate_id=f"{request.scene_id}:{self.key}:1",
                    scene_id=request.scene_id,
                    provider=self.key,
                    source_id=f"{self.key}:1",
                    title=self.title,
                    duration=10.0,
                    score=self.candidate_score,
                    description=self.title,
                )
            ],
        )


def test_strong_local_match_skips_network_providers():
    local = CountingProvider("local", 0.95, "Havana mechanic")
    youtube = CountingProvider("youtube", 0.90, "Havana mechanic")
    service = DiscoveryService(ProviderRegistry([youtube, local]))

    result = service.search_scene(
        demo_scenes()[0],
        SearchOptions(
            provider_keys=("youtube", "local"),
            local_first=True,
            local_accept_score=0.88,
        ),
    )

    assert local.calls == 1
    assert youtube.calls == 0
    assert result.candidates[0].provider == "local"
    assert any("Local-first" in notice for notice in result.notices)


def test_weak_local_match_falls_back_to_network():
    local = CountingProvider("local", 0.10, "unrelated footage")
    youtube = CountingProvider("youtube", 0.90, "Havana mechanic classic car")
    service = DiscoveryService(ProviderRegistry([youtube, local]))

    result = service.search_scene(
        demo_scenes()[0],
        SearchOptions(
            provider_keys=("youtube", "local"),
            local_first=True,
            local_accept_score=0.88,
        ),
    )

    assert local.calls == 1
    assert youtube.calls == 1
    assert {item.provider for item in result.candidates} == {"local", "youtube"}


def test_local_first_can_be_disabled():
    local = CountingProvider("local", 1.0, "Havana mechanic")
    youtube = CountingProvider("youtube", 0.9, "Havana mechanic")
    service = DiscoveryService(ProviderRegistry([youtube, local]))

    service.search_scene(
        demo_scenes()[0],
        SearchOptions(
            provider_keys=("youtube", "local"),
            local_first=False,
        ),
    )

    assert youtube.calls == 1
    assert local.calls == 1
