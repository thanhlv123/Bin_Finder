"""BF-S06: controlled YouTube *discovery* for BF-S04A editorial shots.

Discovery is API metadata only. YouTube audiovisual files are NEVER requested,
streamed, downloaded, cached or handed to the FFmpeg clipper by this module.
CC labels are discovery filters, NOT usage/download clearance.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import SearchRequest
from bin_finder.providers.youtube import YouTubeProvider
from bin_finder.search.editorial_shot_plan import EditorialShot, EditorialShotPlan

_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")
_MAX_CALLS = 3
_ALLOWED = frozenset({"authentic_person", "authentic_event", "location_context",
                     "illustrative_stock", "symbolic"})


class YouTubeShotDiscoveryError(ValueError):
    """Safe error codes only, never raw provider text, URLs or API keys."""


@dataclass(frozen=True)
class YouTubeReferenceHit:
    shot_id: str
    video_id: str
    title: str
    channel: str
    description: str
    watch_url: str
    thumbnail_url: str
    duration_seconds: float
    metadata_license: str
    rights_status: str = "manual-verification-required"
    preview_status: str = "youtube-watch-only"
    footage_verified: bool = False
    acquisition_allowed: bool = False
    clip_export_allowed: bool = False


@dataclass(frozen=True)
class YouTubeShotSearchResult:
    shot_id: str
    status: str
    hits: tuple[YouTubeReferenceHit, ...]
    search_attempts: int
    api_http_requests_confirmed: str = "unknown"
    audiovisual_downloads: int = 0
    user_clips_created: int = 0


def _safe_metadata(text: object, limit=240) -> str:
    if not isinstance(text, str):
        return ""
    # Treat upstream metadata as untrusted data, never HTML/code.
    return "".join(c for c in text if c.isprintable())[:limit]


def _validate_shot(shot: EditorialShot) -> None:
    if not isinstance(shot, EditorialShot) or shot.asset_evidence_type not in _ALLOWED:
        raise YouTubeShotDiscoveryError("shot-not-searchable")
    if not shot.search_queries or not shot.visual_brief:
        raise YouTubeShotDiscoveryError("missing-shot-query")


def _to_reference(shot_id: str, candidate: CandidateRecord) -> YouTubeReferenceHit | None:
    if not isinstance(candidate, CandidateRecord) or candidate.provider != "youtube":
        return None
    if not candidate.source_id.startswith("youtube:"):
        return None
    video_id = candidate.source_id.removeprefix("youtube:")
    if not _ID.fullmatch(video_id):
        return None
    if not isinstance(candidate.duration, (int, float)):
        return None
    # Youtube's CC flag is a *self-reported metadata license*, not cleared
    # footage, not a download link, and not proof of third-party rights.
    metadata_license = (
        "youtube-cc-label-unverified"
        if candidate.rights_status == "creative_commons"
        else "youtube-standard-or-unknown"
    )
    return YouTubeReferenceHit(
        shot_id=shot_id,
        video_id=video_id,
        title=_safe_metadata(candidate.title),
        channel=_safe_metadata(candidate.creator),
        description=_safe_metadata(candidate.description, 500),
        watch_url="https://www.youtube.com/watch?v=" + video_id,
        thumbnail_url=_safe_metadata(candidate.thumbnail_url, 500),
        duration_seconds=max(0.0, float(candidate.duration)),
        metadata_license=metadata_license,
    )


def discover_youtube_for_shot(
    shot: EditorialShot, provider: YouTubeProvider, *,
    approve_youtube_api_search: bool = False,
    max_queries: int = 2,
    max_results: int = 5,
    creative_commons_filter: bool = True,
) -> YouTubeShotSearchResult:
    """Opt-in official YouTube Data API metadata discovery; no content fetch."""
    _validate_shot(shot)
    if not isinstance(provider, YouTubeProvider):
        raise YouTubeShotDiscoveryError("invalid-youtube-provider")
    if type(approve_youtube_api_search) is not bool:
        raise YouTubeShotDiscoveryError("invalid-youtube-approval")
    if (type(max_queries) is not int or not 1 <= max_queries <= _MAX_CALLS
            or type(max_results) is not int or not 1 <= max_results <= 10
            or type(creative_commons_filter) is not bool):
        raise YouTubeShotDiscoveryError("invalid-youtube-search-limits")
    if not approve_youtube_api_search:
        return YouTubeShotSearchResult(
            shot.shot_id, "approval-required", (), 0, "0"
        )
    if not provider.status().configured:
        return YouTubeShotSearchResult(
            shot.shot_id, "youtube-api-key-not-configured", (), 0, "0"
        )

    from bin_finder.providers.base import ProviderError
    seen: set[str] = set()
    hits: list[YouTubeReferenceHit] = []
    attempts = 0
    search_error = False
    for query in shot.search_queries[:max_queries]:
        if len(hits) >= max_results:
            break
        attempts += 1
        try:
            response = provider.search(SearchRequest(
                scene_id=shot.scene_ids[0],
                query=query.text, limit=max_results,
                safe_search=True, creative_commons_only=creative_commons_filter,
                min_height=0,
            ))
        except (ProviderError, OSError, ValueError, TypeError):
            search_error = True
            continue
        for item in response.candidates:
            ref = _to_reference(shot.shot_id, item)
            if ref is None or ref.video_id in seen:
                continue
            seen.add(ref.video_id)
            hits.append(ref)
            if len(hits) >= max_results:
                break
    return YouTubeShotSearchResult(
        shot_id=shot.shot_id,
        status=("references-for-human-review" if hits
                else "provider-error-no-references" if search_error
                else "no-youtube-references"),
        hits=tuple(hits),
        search_attempts=attempts,
    )
