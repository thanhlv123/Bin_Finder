"""BF-S02 opt-in HTTP response-body diagnosis with strict information reduction.

Sends at most ONE minimal provider search GET. The response body is read in
bounded memory and classified to fixed codes; the body, full URL, response
headers, key, traceback, media links and errors are NEVER logged or returned.

This isolated research probe does not alter the production HTTP client.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class ProviderProbeResult:
    provider_calls: int
    status_code: str
    error_hint: str
    candidate_count: int


_PROVIDER_SPEC = {
    "pexels": (
        "https://api.pexels.com/v1/videos/search",
        {"query": "nature", "per_page": 1},
        "videos",
    ),
    "pixabay": (
        "https://pixabay.com/api/videos/",
        {"q": "nature", "per_page": 3},
        "hits",
    ),
}
_MAX_ERROR_BYTES = 2048
_MAX_RESPONSE_BYTES = 512 * 1024


def classify_error_body(raw: bytes) -> str:
    """Allowlisted semantic error hint; never reveal any untrusted body text."""
    if not isinstance(raw, bytes):
        return "unclassified-error-body"
    value = raw[:_MAX_ERROR_BYTES].decode("utf-8", "replace").lower()

    key = r"(?:api[ _-]?key|access[ _-]?token|\bkey\b)"
    bad = r"(?:invalid|expired|revoked|incorrect|unknown|not valid|unrecognized)"
    missing = r"(?:missing|required|not provided|no|must provide)"
    if (re.search(r"\b" + bad + r"\b.{0,50}" + key, value)
            or re.search(key + r".{0,50}\b" + bad + r"\b", value)):
        return "invalid-api-key-indicated"
    if (re.search(r"\b" + missing + r"\b.{0,50}" + key, value)
            or re.search(key + r".{0,50}\b" + missing + r"\b", value)):
        return "missing-api-key-indicated"
    if (re.search(r"\b(?:permission|unauthori[sz]ed|forbidden|access denied)\b", value)):
        return "access-denied-indicated"
    if re.search(r"\b(?:rate limit|too many requests|quota exceeded)\b", value):
        return "rate-limit-indicated"
    if re.search(r"\b(?:captcha|cloudflare|security check|challenge required)\b", value):
        return "edge-challenge-indicated"
    if re.search(r"\b(?:invalid parameter|invalid query|unsupported parameter|bad parameter)\b", value):
        return "invalid-request-parameter-indicated"
    if "<html" in value or "<!doctype html" in value:
        return "html-error-body"
    if value.strip() in {"bad request", "400 bad request"}:
        return "generic-bad-request"
    return "unclassified-error-body"


def probe_minimal_provider(provider: str, api_key: str) -> ProviderProbeResult:
    """One documented minimal search, using the normal Python URL opener.

    The returned category describes a server indication, not a verified
    assertion about which key/parameter is wrong.
    """
    if provider not in _PROVIDER_SPEC:
        raise ValueError("unsupported-provider")
    if not isinstance(api_key, str) or not api_key.strip():
        return ProviderProbeResult(0, "not-configured", "", 0)

    endpoint, defaults, result_field = _PROVIDER_SPEC[provider]
    params = dict(defaults)
    headers = {"User-Agent": "BinFinder/0.1"}
    if provider == "pexels":
        headers["Authorization"] = api_key.strip()
    else:
        params["key"] = api_key.strip()

    url = endpoint + "?" + urlencode(params)
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=15.0) as response:
            body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            return ProviderProbeResult(1, "response-too-large", "", 0)
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict) or not isinstance(
            payload.get(result_field), list
        ):
            return ProviderProbeResult(1, "invalid-provider-result", "", 0)
        count = len(payload[result_field])
        return ProviderProbeResult(1, "ok" if count else "empty", "", count)
    except HTTPError as error:
        try:
            status = int(error.code)
            raw = error.read(_MAX_ERROR_BYTES)
            hint = classify_error_body(raw)
        except Exception:
            status, hint = 0, "unclassified-error-body"
        finally:
            error.close()
        if 400 <= status <= 599:
            return ProviderProbeResult(1, f"http-{status}", hint, 0)
        return ProviderProbeResult(1, "unexpected-http-status", hint, 0)
    except (URLError, TimeoutError, OSError):
        return ProviderProbeResult(1, "network-or-timeout", "", 0)
    except (UnicodeDecodeError, ValueError, TypeError):
        return ProviderProbeResult(1, "invalid-json", "", 0)
    except Exception:
        return ProviderProbeResult(1, "unexpected-provider-error", "", 0)
