"""Coverr metadata discovery; never downloads media."""
from urllib.parse import quote

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus
from bin_finder.providers.http import JsonHttpClient
from bin_finder.providers.normalization import number, text, url


class CoverrProvider:
    key = "coverr"
    display_name = "Coverr"
    SEARCH_URL = "https://api.coverr.co/videos"

    def __init__(self, api_key, http=None):
        self.api_key = api_key.strip()
        self.http = http or JsonHttpClient()

    def status(self):
        return ProviderStatus(self.key, self.display_name, bool(self.api_key),
                              "Sẵn sàng" if self.api_key else "Thiếu BIN_FINDER_COVERR_API_KEY")

    def search(self, request):
        if not self.api_key:
            return ProviderSearchResult(self.key, notice="Coverr API key is not configured")
        payload = self.http.get_json(
            self.SEARCH_URL,
            params={"query": request.query, "page_size": max(1, min(50, request.limit)), "urls": "true"},
            headers={"Authorization": f"Bearer {self.api_key}"}, provider_name=self.display_name,
        )
        hits = payload.get("hits", [])
        candidates = []
        for item in hits if isinstance(hits, list) else []:
            if not isinstance(item, dict):
                continue
            video_id = str(item.get("id") or "") if isinstance(item.get("id"), (str, int)) else ""
            if not video_id:
                continue
            urls = item.get("urls") if isinstance(item.get("urls"), dict) else {}
            author = item.get("author") or item.get("creator") or item.get("user") or ""
            creator = text(author.get("name")) if isinstance(author, dict) else text(author)
            width = int(number(item.get("max_width")) or number(item.get("width")))
            height = int(number(item.get("max_height")) or number(item.get("height")))
            candidates.append(CandidateRecord(
                candidate_id=f"{request.scene_id}:coverr:{video_id}", scene_id=request.scene_id,
                provider=self.key, source_id=f"coverr:{video_id}",
                title=text(item.get("title")) or video_id, duration=number(item.get("duration")), score=0.0,
                rights_status="coverr_license", resolution=f"{width}x{height}" if width and height else "",
                creator=creator, description=text(item.get("description")),
                source_url="https://coverr.co/videos/" + quote(text(item.get("slug")) or video_id, safe=""),
                thumbnail_url=url(item.get("thumbnail")) or url(item.get("poster")),
                preview_url=url(urls.get("mp4_preview")) or url(urls.get("mp4")) or url(urls.get("mp4_download")),
                source_metadata={"license": "Coverr License", "license_url": "https://coverr.co/license",
                                 "attribution_required": False},
            ))
        return ProviderSearchResult(self.key, candidates[:max(0, request.limit)])
