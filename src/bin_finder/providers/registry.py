from __future__ import annotations

from bin_finder.provider_config import ProviderConfig
from bin_finder.providers.base import DiscoveryProvider, ProviderStatus
from bin_finder.providers.local import LocalLibraryProvider
from bin_finder.providers.pexels import PexelsProvider
from bin_finder.providers.pixabay import PixabayProvider
from bin_finder.providers.storyblocks import StoryblocksProvider
from bin_finder.providers.youtube import YouTubeProvider


class ProviderRegistry:
    def __init__(self, providers: list[DiscoveryProvider]):
        self._providers = {provider.key: provider for provider in providers}

    @classmethod
    def from_config(cls, config: ProviderConfig) -> "ProviderRegistry":
        return cls(
            [
                YouTubeProvider(config.youtube_api_key),
                StoryblocksProvider(
                    config.storyblocks_public_key,
                    config.storyblocks_secret_key,
                    config.storyblocks_project_id,
                    config.storyblocks_user_id,
                ),
                PexelsProvider(config.pexels_api_key),
                PixabayProvider(config.pixabay_api_key),
                LocalLibraryProvider(config.local_library_path),
            ]
        )

    def get(self, key: str) -> DiscoveryProvider | None:
        return self._providers.get(key)

    def statuses(self) -> list[ProviderStatus]:
        return [provider.status() for provider in self._providers.values()]

    def keys(self) -> tuple[str, ...]:
        return tuple(self._providers)
