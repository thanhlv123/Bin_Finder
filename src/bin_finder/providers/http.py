from __future__ import annotations

import json
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bin_finder.providers.base import ProviderError



# Fixed known YouTube error reasons only. Never return Google's raw error
# message, request URL, credentials or response body in a report.
_YOUTUBE_REASON_CODES = frozenset({
    "accessNotConfigured", "keyInvalid", "keyExpired", "quotaExceeded",
    "dailyLimitExceeded", "dailyLimitExceededUnreg", "rateLimitExceeded",
    "userRateLimitExceeded", "forbidden", "invalidSearchFilter",
    "invalidFilters", "invalidQuery", "API_KEY_SERVICE_BLOCKED",
    "API_KEY_INVALID", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
})


def _safe_youtube_http_error_reason(exc: HTTPError) -> str:
    try:
        blob = exc.read(16384 + 1)
        if len(blob) > 16384:
            return "unclassified"
        parsed = json.loads(blob.decode("utf-8"))
        error = parsed.get("error")
        if not isinstance(error, dict):
            return "unclassified"
        reasons = [
            item.get("reason")
            for item in error.get("errors", [])[:4]
            if isinstance(item, dict)
        ] if isinstance(error.get("errors"), list) else []
        details = error.get("details")
        if isinstance(details, list):
            reasons.extend(
                x.get("reason") for x in details[:4] if isinstance(x, dict)
            )
        reasons.append(error.get("status"))
        for reason in reasons:
            if isinstance(reason, str) and reason in _YOUTUBE_REASON_CODES:
                return reason
    except (ValueError, TypeError, UnicodeError, OSError, AttributeError):
        pass
    return "unclassified"


class JsonHttpClient:
    """Small stdlib JSON client so F002 adds no runtime dependency."""

    def get_json(
        self,
        base_url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
        provider_name: str = "provider",
    ) -> dict[str, Any]:
        query = urlencode(
            [(key, value) for key, value in (params or {}).items() if value is not None],
            doseq=True,
        )
        url = f"{base_url}?{query}" if query else base_url
        request_headers = {"User-Agent": "BinFinder/0.1", **(headers or {})}
        request = Request(url, headers=request_headers, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read(8 * 1024 * 1024 + 1)
                if len(body) > 8 * 1024 * 1024:
                    raise ProviderError(f"{provider_name}: response too large")
                body = body.decode("utf-8")
        except UnicodeDecodeError:
            raise ProviderError(f"{provider_name}: invalid response encoding") from None
        except HTTPError as exc:
            if provider_name in {"YouTube/search", "YouTube/details"}:
                reason = _safe_youtube_http_error_reason(exc)
                # ProviderError text is bounded and entirely from fixed known
                # codes + integer HTTP status; never raw Google messages.
                raise ProviderError(
                    f"{provider_name}: HTTP {int(exc.code)}; reason={reason}"
                ) from None
            raise ProviderError(f"{provider_name}: HTTP {exc.code}") from None
        except URLError:
            raise ProviderError(f"{provider_name}: không thể kết nối mạng") from None
        except TimeoutError:
            raise ProviderError(f"{provider_name}: hết thời gian chờ") from None

        except (OSError, HTTPException):
            raise ProviderError(f"{provider_name}: network failure") from None

        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, RecursionError):
            raise ProviderError(f"{provider_name}: phản hồi JSON không hợp lệ") from None
        if not isinstance(payload, dict):
            raise ProviderError(f"{provider_name}: phản hồi không hợp lệ")
        return payload
