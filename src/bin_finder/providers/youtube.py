from __future__ import annotations

import re
from typing import Any

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus, SearchRequest
from bin_finder.providers.http import JsonHttpClient


_DURATION_RE = re.compile(r"P(?:(?P<days>\d+)D)?T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?$")


def parse_youtube_duration(value: str) -> float:
    match = _DURATION_RE.fullmatch(value or "")
    if not match:
        return 0.0
    parts = {key: int(raw or 0) for key, raw in match.groupdict().items()}
    return float(parts["days"] * 86400 + parts["hours"] * 3600 + parts["minutes"] * 60 + parts["seconds"])


def _best_thumbnail(snippet: dict[str, Any]) -> str:
    thumbnails = snippet.get("thumbnails") or {}
    if not isinstance(thumbnails, dict):
        return ""
    for key in ("maxres", "standard", "high", "medium", "default"):
        item = thumbnails.get(key)
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    return ""


class YouTubeProvider:
    key = "youtube"
    display_name = "YouTube"
    SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
    VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"

    def __init__(self, api_key: str, http: JsonHttpClient | None = None):
        self.api_key = api_key.strip()
        self.http = http or JsonHttpClient()

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            self.key,
            self.display_name,
            bool(self.api_key),
            "Sẵn sàng" if self.api_key else "Thiếu BIN_FINDER_YOUTUBE_API_KEY",
        )

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        if not self.api_key:
            return ProviderSearchResult(self.key, notice="YouTube chưa cấu hình API key")

        params: dict[str, Any] = {
            "part": "snippet",
            "q": request.query,
            "type": "video",
            "maxResults": max(1, min(request.limit, 50)),
            "safeSearch": "moderate" if request.safe_search else "none",
            "key": self.api_key,
        }
        if request.duration_bucket in {"short", "medium", "long"}:
            params["videoDuration"] = request.duration_bucket
        if request.min_height >= 720:
            params["videoDefinition"] = "high"
        if request.creative_commons_only:
            params["videoLicense"] = "creativeCommon"

        search_payload = self.http.get_json(
            self.SEARCH_URL,
            params=params,
            provider_name="YouTube/search",
        )
        ids: list[str] = []
        for item in search_payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            id_part = item.get("id") or {}
            video_id = id_part.get("videoId") if isinstance(id_part, dict) else None
            if video_id:
                ids.append(str(video_id))
        if not ids:
            return ProviderSearchResult(self.key, [])

        detail_payload = self.http.get_json(
            self.VIDEOS_URL,
            params={
                "part": "snippet,contentDetails,status",
                "id": ",".join(ids),
                "key": self.api_key,
            },
            provider_name="YouTube/details",
        )
        candidates: list[CandidateRecord] = []
        for item in detail_payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("id") or "")
            if not video_id:
                continue
            snippet = item.get("snippet") or {}
            content = item.get("contentDetails") or {}
            status = item.get("status") or {}
            license_value = str(status.get("license") or "youtube")
            rights = "creative_commons" if license_value == "creativeCommon" else "youtube_standard"
            definition = str(content.get("definition") or "").upper()
            candidates.append(
                CandidateRecord(
                    candidate_id=f"{request.scene_id}:youtube:{video_id}",
                    scene_id=request.scene_id,
                    provider=self.key,
                    source_id=f"youtube:{video_id}",
                    title=str(snippet.get("title") or video_id),
                    duration=parse_youtube_duration(str(content.get("duration") or "")),
                    score=0.0,
                    rights_status=rights,
                    resolution="HD" if definition == "HD" else definition,
                    source_url=f"https://www.youtube.com/watch?v={video_id}",
                    thumbnail_url=_best_thumbnail(snippet),
                    preview_url=f"https://www.youtube.com/watch?v={video_id}",
                    creator=str(snippet.get("channelTitle") or ""),
                    description=str(snippet.get("description") or ""),
                    published_at=str(snippet.get("publishedAt") or ""),
                )
            )
        return ProviderSearchResult(self.key, candidates)
