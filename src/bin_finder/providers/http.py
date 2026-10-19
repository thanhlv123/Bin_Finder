from __future__ import annotations

import json
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bin_finder.providers.base import ProviderError


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
