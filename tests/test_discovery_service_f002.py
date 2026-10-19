from bin_finder.demo_data import demo_scenes
from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.service import DiscoveryService, SearchOptions


class FakeProvider:
    key = "youtube"
    display_name = "YouTube"

    def status(self):
        return ProviderStatus(self.key, self.display_name, True, "ready")

    def search(self, request):
        return ProviderSearchResult(
            self.key,
            [CandidateRecord(
                candidate_id=f"{request.scene_id}:youtube:a",
                scene_id=request.scene_id,
                provider="youtube",
                source_id="youtube:a",
                title="Havana mechanic classic car",
                duration=300,
                score=0,
                description="Cuba street mechanic",
            )],
        )


def test_discovery_service_aggregates_dedupes_and_defers_news():
    service = DiscoveryService(ProviderRegistry([FakeProvider()]))
    scene = demo_scenes()[0]
    result = service.search_scene(
        scene,
        SearchOptions(provider_keys=("youtube", "news"), limit=10, multiple_queries=True),
    )
    assert result.scene_id == scene.scene_id
    assert len(result.candidates) == 1
    assert result.candidates[0].score > 0
    assert any("Báo điện tử" in notice for notice in result.notices)
    assert len(result.query_texts) == 3


def test_discovery_service_no_sources_is_nonfatal():
    service = DiscoveryService(ProviderRegistry([]))
    result = service.search_scene(demo_scenes()[0], SearchOptions(provider_keys=()))
    assert result.candidates == []
    assert result.notices == ["Chưa chọn nguồn tìm kiếm."]
