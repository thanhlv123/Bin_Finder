from __future__ import annotations

import json
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
        request = Request(url, headers=headers or {}, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            raise ProviderError(f"{provider_name}: HTTP {exc.code}") from None
        except URLError:
            raise ProviderError(f"{provider_name}: không thể kết nối mạng") from None
        except TimeoutError:
            raise ProviderError(f"{provider_name}: hết thời gian chờ") from None

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            raise ProviderError(f"{provider_name}: phản hồi JSON không hợp lệ") from None
        if not isinstance(payload, dict):
            raise ProviderError(f"{provider_name}: phản hồi không hợp lệ")
        return payload
