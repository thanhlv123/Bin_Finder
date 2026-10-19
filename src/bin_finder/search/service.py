from __future__ import annotations

import re
from dataclasses import dataclass, replace

from bin_finder.models import CandidateRecord, SceneRecord
from bin_finder.providers.base import ProviderError, SearchRequest
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.query_builder import build_scene_queries


_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(value) if len(token) > 1}


def _metadata_score(
    query: str,
    candidate: CandidateRecord,
    provider_rank: int,
) -> float:
    wanted = _tokens(query)
    text = f"{candidate.title} {candidate.description} {candidate.creator}"
    available = _tokens(text)
    overlap = len(wanted & available) / max(1, len(wanted))
    rank_bonus = max(0.0, 0.18 - provider_rank * 0.01)
    metadata_score = min(0.99, 0.42 + overlap * 0.40 + rank_bonus)
    return round(max(float(candidate.score or 0.0), metadata_score), 3)


@dataclass(frozen=True)
class SearchOptions:
    provider_keys: tuple[str, ...]
    limit: int = 20
    orientation: str = "any"
    min_width: int = 0
    min_height: int = 720
    duration_bucket: str = "any"
    creative_commons_only: bool = False
    multiple_queries: bool = False
    local_first: bool = True
    local_accept_score: float = 0.88


@dataclass
class SearchBatchResult:
    scene_id: str
    query_texts: list[str]
    candidates: list[CandidateRecord]
    notices: list[str]


class DiscoveryService:
    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def _search_provider(
        self,
        provider_key: str,
        scene: SceneRecord,
        queries: list[str],
        options: SearchOptions,
        notices: list[str],
    ) -> list[CandidateRecord]:
        if provider_key == "news":
            notices.append("Báo điện tử: tạm thời chưa hỗ trợ.")
            return []

        provider = self.registry.get(provider_key)
        if provider is None:
            notices.append(f"{provider_key}: provider chưa được đăng ký.")
            return []

        per_provider_limit = max(5, options.limit)
        provider_candidates: list[CandidateRecord] = []
        for query in queries:
            request = SearchRequest(
                scene_id=scene.scene_id,
                query=query,
                limit=per_provider_limit,
                orientation=options.orientation,
                min_width=options.min_width,
                min_height=options.min_height,
                duration_bucket=options.duration_bucket,
                creative_commons_only=(
                    options.creative_commons_only
                    and provider_key == "youtube"
                ),
            )
            try:
                result = provider.search(request)
            except ProviderError as exc:
                notices.append(str(exc))
                break
            if result.notice:
                notices.append(result.notice)
            provider_candidates.extend(result.candidates)

        seen_source_ids: set[str] = set()
        ranked: list[CandidateRecord] = []
        for rank, candidate in enumerate(provider_candidates):
            if candidate.source_id in seen_source_ids:
                continue
            seen_source_ids.add(candidate.source_id)
            ranked.append(
                replace(
                    candidate,
                    score=_metadata_score(queries[0], candidate, rank),
                )
            )
        return ranked

    def search_scene(
        self,
        scene: SceneRecord,
        options: SearchOptions,
    ) -> SearchBatchResult:
        queries = build_scene_queries(
            scene,
            max_queries=3 if options.multiple_queries else 1,
        )
        notices: list[str] = []
        gathered: list[CandidateRecord] = []

        if not options.provider_keys:
            return SearchBatchResult(
                scene.scene_id,
                queries,
                [],
                ["Chưa chọn nguồn tìm kiếm."],
            )

        provider_keys = list(options.provider_keys)
        if options.local_first and "local" in provider_keys:
            provider_keys.remove("local")
            local_candidates = self._search_provider(
                "local",
                scene,
                queries,
                options,
                notices,
            )
            gathered.extend(local_candidates)
            best_local = max(
                (candidate.score for candidate in local_candidates),
                default=0.0,
            )
            if best_local >= options.local_accept_score:
                notices.append(
                    f"Local-first: đạt ngưỡng {best_local:.2f}; "
                    "bỏ qua nguồn mạng cho cảnh này."
                )
                return self._finalize(
                    scene.scene_id,
                    queries,
                    gathered,
                    notices,
                    options.limit,
                )

        for provider_key in provider_keys:
            gathered.extend(
                self._search_provider(
                    provider_key,
                    scene,
                    queries,
                    options,
                    notices,
                )
            )

        return self._finalize(
            scene.scene_id,
            queries,
            gathered,
            notices,
            options.limit,
        )

    @staticmethod
    def _finalize(
        scene_id: str,
        queries: list[str],
        gathered: list[CandidateRecord],
        notices: list[str],
        limit: int,
    ) -> SearchBatchResult:
        deduped: dict[tuple[str, str], CandidateRecord] = {}
        for candidate in gathered:
            key = (candidate.provider, candidate.source_id)
            existing = deduped.get(key)
            if existing is None or candidate.score > existing.score:
                deduped[key] = candidate

        ordered = sorted(
            deduped.values(),
            key=lambda item: (
                -item.score,
                item.provider,
                item.title.casefold(),
            ),
        )
        return SearchBatchResult(
            scene_id,
            queries,
            ordered[:limit],
            list(dict.fromkeys(notices)),
        )
