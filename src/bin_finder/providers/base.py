from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from bin_finder.models import CandidateRecord


class ProviderError(RuntimeError):
    """Safe provider error whose message must not contain credentials."""


@dataclass(frozen=True)
class SearchRequest:
    scene_id: str
    query: str
    limit: int = 20
    orientation: str = "any"
    min_width: int = 0
    min_height: int = 0
    duration_bucket: str = "any"
    creative_commons_only: bool = False
    safe_search: bool = True


@dataclass(frozen=True)
class ProviderStatus:
    key: str
    display_name: str
    configured: bool
    detail: str = ""


@dataclass
class ProviderSearchResult:
    provider_key: str
    candidates: list[CandidateRecord] = field(default_factory=list)
    notice: str = ""


class DiscoveryProvider(Protocol):
    key: str
    display_name: str

    def status(self) -> ProviderStatus: ...

    def search(self, request: SearchRequest) -> ProviderSearchResult: ...
