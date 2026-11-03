"""Bounded Wikimedia Commons video metadata discovery."""
import html
import json
import re
import threading
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderError, ProviderSearchResult, ProviderStatus
from bin_finder.providers.normalization import number


def safe_url(value, host):
    try:
        parsed = urlsplit(value if isinstance(value, str) else "")
        if parsed.query:
            if host != "upload.wikimedia.org" or len(parsed.query) > 512:
                return ""
            pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=3)
            if (len({key for key, _ in pairs}) != len(pairs)
                    or any(key not in {"utm_source", "utm_campaign", "utm_content"}
                           or len(content) > 100 for key, content in pairs)):
                return ""
        if (parsed.scheme == "https" and parsed.hostname == host and not parsed.username
                and not parsed.password and parsed.port in (None, 443)
                and not parsed.fragment):
            return value.split("?", 1)[0]
    except ValueError:
        pass
    return ""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProviderError("Commons: redirect refused")


class CommonsHttp:
    def get_json(self, base_url, *, params, **kwargs):
        if base_url != CommonsProvider.API:
            raise ProviderError("Commons: invalid API")
        request = Request(base_url + "?" + urlencode(params), headers={"User-Agent": "BinFinder/0.2"})
        try:
            with build_opener(NoRedirect()).open(request, timeout=15) as response:
                body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ProviderError("Commons: response too large")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ProviderError("Commons: invalid response")
            return payload
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("Commons: metadata unavailable") from None


class CommonsProvider:
    key = "commons"
    display_name = "Wikimedia Commons"
    API = "https://commons.wikimedia.org/w/api.php"

    def __init__(self, http=None, max_requests=1000):
        if type(max_requests) is not int or not 1 <= max_requests <= 5000:
            raise ValueError("Commons: invalid request budget")
        self.http = http or CommonsHttp()
        self.remaining = max_requests
        self._lock = threading.Lock()

    def status(self):
        return ProviderStatus(self.key, self.display_name, True, "Public metadata API")

    def _query(self, params, scene_id):
        with self._lock:
            if self.remaining <= 0:
                raise ProviderError("Commons: request budget exhausted")
            self.remaining -= 1
        payload = self.http.get_json(self.API, params={
            "action": "query", "format": "json", "formatversion": 2, "prop": "imageinfo",
            "iiprop": "url|size|mime|sha1|timestamp|extmetadata", **params,
        })
        if not isinstance(payload, dict) or "error" in payload:
            raise ProviderError("Commons: invalid response")
        query = payload.get("query", {})
        pages = query.get("pages", []) if isinstance(query, dict) else []
        if not isinstance(pages, list) or len(pages) > 50:
            raise ProviderError("Commons: invalid pages")
        candidates = []
        for page in pages:
            if not isinstance(page, dict):
                continue
            infos = page.get("imageinfo")
            if not isinstance(infos, list) or not infos or not isinstance(infos[0], dict):
                continue
            info = infos[0]
            if not str(info.get("mime", "")).startswith("video/"):
                continue
            page_id, title = page.get("pageid"), page.get("title", "")
            if type(page_id) is not int or page_id <= 0 or not isinstance(title, str) or not title.startswith("File:"):
                continue
            media = safe_url(info.get("url"), "upload.wikimedia.org")
            source = safe_url(info.get("descriptionurl"), "commons.wikimedia.org")
            if not media or not source:
                continue
            metadata = info.get("extmetadata", {})

            def clean(key):
                entry = metadata.get(key, {}) if isinstance(metadata, dict) else {}
                value = entry.get("value", "") if isinstance(entry, dict) else ""
                return html.unescape(re.sub(r"<[^>]*>", "", str(value)))[:4000].strip()

            license_name = clean("LicenseShortName")
            rights = clean("License").lower() or license_name.lower().replace(" ", "-")
            if license_name.lower() in {"public domain", "public-domain"}:
                rights = "public-domain"
            width, height = int(number(info.get("width"))), int(number(info.get("height")))
            candidates.append(CandidateRecord(
                candidate_id=f"{scene_id}:commons:{page_id}", scene_id=scene_id, provider=self.key,
                source_id=f"commons:{page_id}", title=title, duration=number(info.get("duration")), score=0.0,
                rights_status=rights or "unknown", resolution=f"{width}x{height}" if width and height else "",
                source_url=source, preview_url=media, creator=clean("Artist"), description=clean("ImageDescription"),
                source_metadata={"license": license_name or "unknown", "license_url": clean("LicenseUrl"),
                                 "attribution_required": clean("AttributionRequired").lower() != "false",
                                 "credit": clean("Credit"), "file_title": title,
                                 "restrictions": clean("Restrictions"), "sha1": info.get("sha1", ""),
                                 "mime": info.get("mime"), "usage_authorization": "unknown"},
            ))
        return candidates

    def search(self, request):
        if not request.query.strip():
            raise ProviderError("Commons: empty query")
        limit = max(1, min(request.limit, 20))
        found = self._query({"generator": "search", "gsrsearch": request.query[:200] + " filetype:video",
                             "gsrnamespace": 6, "gsrlimit": limit}, request.scene_id)
        return ProviderSearchResult(self.key, found[:limit])

    def resolve(self, titles, scene_id="resolve"):
        if (not isinstance(titles, (list, tuple)) or not 1 <= len(titles) <= 20
                or any(not isinstance(t, str) or not t.startswith("File:") or len(t) > 300 or "|" in t for t in titles)):
            raise ProviderError("Commons: invalid titles")
        found = self._query({"titles": "|".join(titles)}, scene_id)
        if any(c.source_metadata["file_title"] not in titles for c in found):
            raise ProviderError("Commons: title mismatch")
        return found
