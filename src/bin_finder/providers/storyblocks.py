from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Callable

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus, SearchRequest
from bin_finder.providers.http import JsonHttpClient


class StoryblocksProvider:
    key = "storyblocks"
    display_name = "Storyblocks"
    SEARCH_URL = "https://api.storyblocks.com/api/v2/videos/search"
    RESOURCE = "/api/v2/videos/search"

    def __init__(
        self,
        public_key: str,
        secret_key: str,
        project_id: str,
        user_id: str,
        http: JsonHttpClient | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.public_key = public_key.strip()
        self.secret_key = secret_key.strip()
        self.project_id = project_id.strip()
        self.user_id = user_id.strip()
        self.http = http or JsonHttpClient()
        self.clock = clock

    def _configured(self) -> bool:
        return all((self.public_key, self.secret_key, self.project_id, self.user_id))

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            self.key,
            self.display_name,
            self._configured(),
            "Sẵn sàng" if self._configured() else "Thiếu Storyblocks API credentials/project/user id",
        )

    def _auth(self, expires: int) -> str:
        key = f"{self.secret_key}{expires}".encode("utf-8")
        return hmac.new(key, self.RESOURCE.encode("utf-8"), hashlib.sha256).hexdigest()

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        if not self._configured():
            return ProviderSearchResult(self.key, notice="Storyblocks chưa cấu hình đầy đủ API credentials")
        expires = int(self.clock()) + 3600
        orientation = {
            "landscape": "horizontal",
            "portrait": "vertical",
            "square": "all",
        }.get(request.orientation, "all")
        params: dict[str, Any] = {
            "APIKEY": self.public_key,
            "EXPIRES": str(expires),
            "HMAC": self._auth(expires),
            "project_id": self.project_id,
            "user_id": self.user_id,
            "keywords": request.query,
            "content_type": "footage",
            "page": 1,
            "results_per_page": max(1, min(request.limit, 100)),
            "safe_search": "true" if request.safe_search else "false",
            "orientation": orientation,
            "extended": "isEditorial,maxResolution,hasTalentReleased,hasPropertyReleased,durationMs,description",
        }
        payload = self.http.get_json(
            self.SEARCH_URL,
            params=params,
            provider_name=self.display_name,
        )
        candidates: list[CandidateRecord] = []
        for item in payload.get("results") or []:
            if not isinstance(item, dict):
                continue
            stock_id = str(item.get("id") or "")
            if not stock_id:
                continue
            previews = item.get("preview_urls") or {}
            preview_url = ""
            if isinstance(previews, dict):
                for key in ("_720p", "_480p", "_360p", "_180p"):
                    if previews.get(key):
                        preview_url = str(previews[key])
                        break
            editorial = bool(item.get("isEditorial") or item.get("is_editorial"))
            rights = "storyblocks_editorial" if editorial else "storyblocks_license_required"
            resolution = str(item.get("maxResolution") or item.get("quality") or "")
            candidates.append(
                CandidateRecord(
                    candidate_id=f"{request.scene_id}:storyblocks:{stock_id}",
                    scene_id=request.scene_id,
                    provider=self.key,
                    source_id=f"storyblocks:{stock_id}",
                    title=str(item.get("title") or f"Storyblocks video {stock_id}"),
                    duration=float(item.get("duration") or 0.0),
                    score=0.0,
                    rights_status=rights,
                    resolution=resolution,
                    source_url="",
                    thumbnail_url=str(item.get("thumbnail_url") or ""),
                    preview_url=preview_url,
                    description=str(item.get("description") or ""),
                )
            )
        return ProviderSearchResult(self.key, candidates)
