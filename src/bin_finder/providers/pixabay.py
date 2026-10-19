from __future__ import annotations

from typing import Any

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus, SearchRequest
from bin_finder.providers.http import JsonHttpClient
from bin_finder.providers.normalization import asset_id, number, records, text, url


class PixabayProvider:
    key = "pixabay"
    display_name = "Pixabay"
    SEARCH_URL = "https://pixabay.com/api/videos/"

    def __init__(self, api_key: str, http: JsonHttpClient | None = None):
        self.api_key = api_key.strip()
        self.http = http or JsonHttpClient()

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            self.key,
            self.display_name,
            bool(self.api_key),
            "Sẵn sàng" if self.api_key else "Thiếu BIN_FINDER_PIXABAY_API_KEY",
        )

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        if not self.api_key:
            return ProviderSearchResult(self.key, notice="Pixabay chưa cấu hình API key")
        params: dict[str, Any] = {
            "key": self.api_key,
            "q": request.query[:100],
            "video_type": "all",
            "page": 1,
            "per_page": max(3, min(request.limit, 200)),
            "safesearch": "true" if request.safe_search else "false",
        }
        if request.min_width:
            params["min_width"] = request.min_width
        if request.min_height:
            params["min_height"] = request.min_height

        payload = self.http.get_json(
            self.SEARCH_URL,
            params=params,
            provider_name=self.display_name,
            timeout=15.0,
        )
        candidates: list[CandidateRecord] = []
        for item in records(payload, "hits", self.display_name)[:max(0, request.limit)]:
            video_id = asset_id(item.get("id"))
            if not video_id:
                continue
            videos = item.get("videos") or {}
            rendition: dict[str, Any] = {}
            if isinstance(videos, dict):
                for key in ("large", "medium", "small", "tiny"):
                    candidate = videos.get(key)
                    if isinstance(candidate, dict) and url(candidate.get("url")):
                        rendition = candidate
                        break
            width = int(number(rendition.get("width")))
            height = int(number(rendition.get("height")))
            tags = text(item.get("tags")).strip()
            candidates.append(
                CandidateRecord(
                    candidate_id=f"{request.scene_id}:pixabay:{video_id}",
                    scene_id=request.scene_id,
                    provider=self.key,
                    source_id=f"pixabay:{video_id}",
                    title=tags or f"Pixabay video {video_id}",
                    duration=number(item.get("duration")),
                    score=0.0,
                    rights_status="pixabay_content_license",
                    resolution=f"{width}x{height}" if width and height else "",
                    source_url=url(item.get("pageURL")),
                    thumbnail_url=url(rendition.get("thumbnail")),
                    preview_url=url(rendition.get("url")),
                    source_metadata={
                        "asset_id": video_id, "creator_id": asset_id(item.get("user_id")),
                        "rendition": key if rendition else "",
                        "renditions": {name: {"url": url(value.get("url")),
                            "width": int(number(value.get("width"))), "height": int(number(value.get("height"))),
                            "thumbnail": url(value.get("thumbnail"))}
                            for name, value in videos.items() if name in {"large", "medium", "small", "tiny"} and isinstance(value, dict)} if isinstance(videos, dict) else {},
                        "license_basis": "provider-defined", "usage_authorization": "unknown",
                        "license_url": "https://pixabay.com/service/license-summary/",
                    },
                    creator=text(item.get("user")),
                    description=tags,
                )
            )
        return ProviderSearchResult(self.key, candidates)
