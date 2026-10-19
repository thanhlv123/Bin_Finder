from __future__ import annotations

from typing import Any

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus, SearchRequest
from bin_finder.providers.http import JsonHttpClient
from bin_finder.providers.normalization import asset_id, number, records, text, url


class PexelsProvider:
    key = "pexels"
    display_name = "Pexels"
    SEARCH_URL = "https://api.pexels.com/v1/videos/search"

    def __init__(self, api_key: str, http: JsonHttpClient | None = None):
        self.api_key = api_key.strip()
        self.http = http or JsonHttpClient()

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            self.key,
            self.display_name,
            bool(self.api_key),
            "Sẵn sàng" if self.api_key else "Thiếu BIN_FINDER_PEXELS_API_KEY",
        )

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        if not self.api_key:
            return ProviderSearchResult(self.key, notice="Pexels chưa cấu hình API key")
        params: dict[str, Any] = {
            "query": request.query,
            "per_page": max(1, min(request.limit, 80)),
            "page": 1,
        }
        if request.orientation in {"landscape", "portrait", "square"}:
            params["orientation"] = request.orientation
        if request.min_height >= 2160:
            params["size"] = "large"
        elif request.min_height >= 1080:
            params["size"] = "medium"
        elif request.min_height >= 720:
            params["size"] = "small"

        payload = self.http.get_json(
            self.SEARCH_URL,
            params=params,
            headers={"Authorization": self.api_key},
            provider_name=self.display_name,
            timeout=15.0,
        )
        candidates: list[CandidateRecord] = []
        for item in records(payload, "videos", self.display_name)[:max(0, request.limit)]:
            video_id = asset_id(item.get("id"))
            if not video_id:
                continue
            user = item.get("user") if isinstance(item.get("user"), dict) else {}
            raw_files = item.get("video_files")
            files = [entry for entry in raw_files if isinstance(entry, dict) and url(entry.get("link"))
                     and text(entry.get("file_type")) in {"", "video/mp4"}] if isinstance(raw_files, list) else []
            files.sort(key=lambda entry: (-number(entry.get("width")) * number(entry.get("height")),
                                          url(entry.get("link")), str(entry.get("id", ""))))
            best = files[0] if files else {}
            width = int(number(best.get("width")) or number(item.get("width")))
            height = int(number(best.get("height")) or number(item.get("height")))
            resolution = f"{width}x{height}" if width and height else ""
            title = (url(item.get("url")) or f"Pexels video {video_id}").rstrip("/").split("/")[-1].replace("-", " ")
            candidates.append(
                CandidateRecord(
                    candidate_id=f"{request.scene_id}:pexels:{video_id}",
                    scene_id=request.scene_id,
                    provider=self.key,
                    source_id=f"pexels:{video_id}",
                    title=title or f"Pexels video {video_id}",
                    duration=number(item.get("duration")),
                    score=0.0,
                    rights_status="pexels_license",
                    resolution=resolution,
                    source_url=url(item.get("url")),
                    thumbnail_url=url(item.get("image")),
                    preview_url=url(best.get("link")),
                    source_metadata={
                        "asset_id": video_id, "creator_id": asset_id(user.get("id")),
                        "creator_url": url(user.get("url")),
                        "renditions": [{"id": asset_id(f.get("id")), "url": url(f.get("link")),
                                        "width": int(number(f.get("width"))), "height": int(number(f.get("height")))} for f in files],
                        "license_basis": "provider-defined", "usage_authorization": "unknown",
                        "license_url": "https://www.pexels.com/license/",
                    },
                    creator=text(user.get("name")),
                )
            )
        return ProviderSearchResult(self.key, candidates)
