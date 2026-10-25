"""BF-S02 research-only slot-aware footage discovery.

Explicit opt-in is mandatory for provider calls. All provider adapters and
their authentication remain unchanged. This module never downloads, approves,
re-encodes, ranks by vision, modifies production state, or writes user files.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Sequence

from bin_finder.models import CandidateRecord, SceneRecord
from bin_finder.providers.base import ProviderError, ProviderSearchResult, SearchRequest
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.visual_search_contract import (
    SemanticSearchPlan, SlotSearchRequest, parse_semantic_search_plan,
)


class SlotSearchError(ValueError):
    """Stable diagnostic code; no provider raw errors or user text are exposed."""


_HTTP_PATTERN = re.compile(r"^(?:Pexels|Pixabay): HTTP ([45][0-9]{2})$")

_SAFE_UPSTREAM_ERRORS = {
    "invalid response encoding": "invalid-encoding",
    "response too large": "response-too-large",
    "không thể kết nối mạng": "network-unreachable",
    "hết thời gian chờ": "timeout",
    "network failure": "network-failure",
    "phản hồi JSON không hợp lệ": "invalid-json",
    "phản hồi không hợp lệ": "invalid-response",
}


def safe_provider_error_code(exc: ProviderError) -> str:
    """Classify only known sanitized client errors, never print raw exceptions.

    Codes are suitable for public reports, even if an unknown provider raises
    an exception embedding credentials, query strings or signed media URLs.
    """
    value = str(exc)
    match = _HTTP_PATTERN.fullmatch(value)
    if match:
        return "http-" + match.group(1)
    for name in ("Pexels", "Pixabay"):
        prefix = name + ": "
        if value.startswith(prefix):
            return _SAFE_UPSTREAM_ERRORS.get(
                value[len(prefix):], "unknown-provider-error"
            )
    return "unknown-provider-error"


@dataclass(frozen=True)
class SlotSearchOptions:
    provider_keys: tuple[str, ...]
    per_query_limit: int = 5
    max_candidates_per_slot: int = 30
    orientation: str = "any"
    min_height: int = 720
    max_calls: int = 18

    def validate(self, slot_count: int) -> None:
        if (not isinstance(self.provider_keys, tuple)
                or not 1 <= len(self.provider_keys) <= 3
                or len(set(self.provider_keys)) != len(self.provider_keys)
                or any(not isinstance(k, str) or not k or len(k) > 40
                       for k in self.provider_keys)):
            raise SlotSearchError("invalid-provider-keys")
        if (type(self.per_query_limit) is not int
                or not 1 <= self.per_query_limit <= 20
                or type(self.max_candidates_per_slot) is not int
                or not 1 <= self.max_candidates_per_slot <= 60
                or self.orientation not in {"any", "landscape", "portrait", "square"}
                or type(self.min_height) is not int
                or not 0 <= self.min_height <= 4320
                or type(self.max_calls) is not int
                or not 1 <= self.max_calls <= 18):
            raise SlotSearchError("invalid-search-options")
        if slot_count * len(self.provider_keys) * 3 > self.max_calls:
            raise SlotSearchError("search-budget-exceeded")


@dataclass(frozen=True)
class CandidateHit:
    """Candidate identity is (provider, source_id), within an explicit slot."""
    slot_id: str
    beat_id: str
    scene_ids: tuple[str, ...]
    candidate: CandidateRecord
    matched_axes: tuple[str, ...]
    returned_order: int

    @property
    def key(self) -> tuple[str, str]:
        return (self.candidate.provider, self.candidate.source_id)


@dataclass(frozen=True)
class SearchAttempt:
    slot_id: str
    provider_key: str
    axis: str
    status: str
    received: int
    error_code: str = ""


@dataclass(frozen=True)
class SlotSearchResult:
    slot_id: str
    hits: tuple[CandidateHit, ...]
    attempts: tuple[SearchAttempt, ...]

    @property
    def status(self) -> str:
        if self.hits:
            return "candidates-unverified"
        if any(a.status in {"provider-error", "invalid-provider-result",
                            "invalid-provider-status"} for a in self.attempts):
            return "technical-error-no-candidates"
        if self.attempts and all(
            a.status == "not-configured" for a in self.attempts
        ):
            return "provider-unavailable"
        return "no-candidates-found"


@dataclass(frozen=True)
class SearchRun:
    plan_id: str
    source_digest: str
    slots: tuple[SlotSearchResult, ...]
    skipped_slots: tuple[str, ...]
    provider_calls: int

    def slot(self, slot_id: str) -> SlotSearchResult:
        for result in self.slots:
            if result.slot_id == slot_id:
                return result
        raise SlotSearchError("unknown-search-slot")


class SlotCandidateSearch:
    """Reads BF-S01 search-only requests; never calls scene-level lexical search."""

    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    def search(
        self,
        plan: SemanticSearchPlan,
        scenes: Sequence[SceneRecord],
        options: SlotSearchOptions,
        *,
        approve_provider_calls: bool = False,
    ) -> SearchRun:
        if not isinstance(plan, SemanticSearchPlan):
            raise SlotSearchError("invalid-search-plan")
        if (parse_semantic_search_plan(plan.to_mapping(), scenes) != plan):
            raise SlotSearchError("invalid-search-plan")
        requests = plan.search_requests()
        options.validate(len(requests))
        if type(approve_provider_calls) is not bool or not approve_provider_calls:
            raise SlotSearchError("provider-calls-not-approved")
        results: list[SlotSearchResult] = []
        calls = 0
        for slot in requests:
            # Deduplicate within one slot only. Do not merge different
            # narration/visual slots which happen to return the same asset.
            found: dict[tuple[str, str], CandidateHit] = {}
            attempts: list[SearchAttempt] = []
            for provider_key in options.provider_keys:
                provider = self.registry.get(provider_key)
                for query in slot.queries:
                    if provider is None:
                        attempts.append(SearchAttempt(
                            slot.slot_id, provider_key, query.axis,
                            "not-configured", 0,
                        ))
                        continue
                    try:
                        status = provider.status()
                        if not status.configured:
                            attempts.append(SearchAttempt(
                                slot.slot_id, provider_key, query.axis,
                                "not-configured", 0,
                            ))
                            continue
                    except (ValueError, TypeError, AttributeError):
                        attempts.append(SearchAttempt(
                            slot.slot_id, provider_key, query.axis,
                            "invalid-provider-status", 0,
                        ))
                        continue

                    request = SearchRequest(
                        scene_id=slot.scene_ids[0],
                        query=query.text,
                        limit=options.per_query_limit,
                        orientation=options.orientation,
                        min_height=options.min_height,
                    )
                    calls += 1
                    try:
                        response = provider.search(request)
                    except ProviderError as exc:
                        attempts.append(SearchAttempt(
                            slot.slot_id, provider_key, query.axis,
                            "provider-error", 0, safe_provider_error_code(exc),
                        ))
                        # Different axes and providers remain eligible.
                        continue
                    if (not isinstance(response, ProviderSearchResult)
                            or response.provider_key != provider_key
                            or not isinstance(response.candidates, list)):
                        attempts.append(SearchAttempt(
                            slot.slot_id, provider_key, query.axis,
                            "invalid-provider-result", 0,
                        ))
                        continue
                    received = 0
                    for candidate in response.candidates[:options.per_query_limit]:
                        if (not isinstance(candidate, CandidateRecord)
                                or candidate.provider != provider_key
                                or candidate.scene_id != slot.scene_ids[0]
                                or not isinstance(candidate.source_id, str)
                                or not candidate.source_id
                                or len(candidate.source_id) > 300):
                            continue
                        received += 1
                        key = (candidate.provider, candidate.source_id)
                        if key in found:
                            previous = found[key]
                            if query.axis not in previous.matched_axes:
                                found[key] = replace(
                                    previous,
                                    matched_axes=previous.matched_axes + (query.axis,),
                                )
                        elif len(found) < options.max_candidates_per_slot:
                            found[key] = CandidateHit(
                                slot_id=slot.slot_id,
                                beat_id=slot.beat_id,
                                scene_ids=slot.scene_ids,
                                candidate=candidate,
                                matched_axes=(query.axis,),
                                returned_order=len(found),
                            )
                    attempts.append(SearchAttempt(
                        slot.slot_id, provider_key, query.axis,
                        "ok" if received else "empty", received,
                    ))
            results.append(SlotSearchResult(
                slot_id=slot.slot_id,
                hits=tuple(found.values()),
                attempts=tuple(attempts),
            ))
        return SearchRun(
            plan_id=plan.plan_id,
            source_digest=plan.source_digest,
            slots=tuple(results),
            skipped_slots=tuple(
                item.slot_id for item in plan.slots if item.action != "search"
            ),
            provider_calls=calls,
        )
