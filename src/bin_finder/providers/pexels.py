from __future__ import annotations

from typing import Any

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus, SearchRequest
from bin_finder.providers.http import JsonHttpClient


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
        )
        candidates: list[CandidateRecord] = []
        for item in payload.get("videos") or []:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("id") or "")
            if not video_id:
                continue
            user = item.get("user") or {}
            files = [entry for entry in (item.get("video_files") or []) if isinstance(entry, dict)]
            files.sort(key=lambda entry: int(entry.get("width") or 0) * int(entry.get("height") or 0), reverse=True)
            best = files[0] if files else {}
            width = int(best.get("width") or 0)
            height = int(best.get("height") or 0)
            resolution = f"{width}x{height}" if width and height else ""
            title = str(item.get("url") or f"Pexels video {video_id}").rstrip("/").split("/")[-1].replace("-", " ")
            candidates.append(
                CandidateRecord(
                    candidate_id=f"{request.scene_id}:pexels:{video_id}",
                    scene_id=request.scene_id,
                    provider=self.key,
                    source_id=f"pexels:{video_id}",
                    title=title or f"Pexels video {video_id}",
                    duration=float(item.get("duration") or 0.0),
                    score=0.0,
                    rights_status="pexels_license",
                    resolution=resolution,
                    source_url=str(item.get("url") or ""),
                    thumbnail_url=str(item.get("image") or ""),
                    preview_url=str(best.get("link") or ""),
                    creator=str(user.get("name") or ""),
                )
            )
        return ProviderSearchResult(self.key, candidates)
