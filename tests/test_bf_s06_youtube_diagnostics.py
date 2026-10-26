"""BF-S06R: sanitized YouTube API diagnostics on offline simulated failures."""
from __future__ import annotations

from io import BytesIO
import json
from urllib.error import HTTPError

import pytest

from bin_finder.providers.base import ProviderError
from bin_finder.providers.http import JsonHttpClient
from bin_finder.providers.youtube import YouTubeProvider
from bin_finder.search.youtube_shot_discovery import (
    _safe_youtube_error_code, discover_youtube_for_shot,
)
from bin_finder.search.youtube_shot_smoke import main
from test_bf_s06_youtube_shot_sourcing import shot


class FailHttp:
    def __init__(self, failure):
        self.failure = failure
        self.calls = []

    def get_json(self, base_url, *, params=None, **kw):
        self.calls.append(base_url)
        raise self.failure


@pytest.mark.parametrize("body,status,expected", [
    ({"error": {"errors": [{"reason": "accessNotConfigured"}]}},
     403, "api-not-enabled"),
    ({"error": {"errors": [{"reason": "keyInvalid"}]}},
     400, "invalid-api-key"),
    ({"error": {"errors": [{"reason": "quotaExceeded"}]}},
     403, "quota-exceeded"),
    ({"error": {"errors": [{"reason": "invalidSearchFilter"}]}},
     400, "invalid-search-filter"),
    ({"error": {"details": [{"reason": "API_KEY_SERVICE_BLOCKED"}]}},
     403, "api-key-service-blocked"),
    ({"error": {"status": "PERMISSION_DENIED"}},
     403, "permission-denied"),
    ({"error": {"errors": [{"reason": "SECRET_API_KEY_GOES_HERE"}],
                "message": "SECRET_API_KEY_GOES_HERE"}},
     403, "unclassified"),
])
def test_google_error_reason_is_whitelisted_and_never_reveals_raw_data(
    monkeypatch, body, status, expected,
):
    fake_body = json.dumps(body).encode("utf-8")
    def fail(req, timeout):
        assert req.full_url.startswith("https://www.googleapis.com/youtube/v3/")
        raise HTTPError(
            url="https://secret.test?key=SECRET_API_KEY_GOES_HERE",
            code=status, msg="SECRET_API_KEY_GOES_HERE",
            hdrs={}, fp=BytesIO(fake_body),
        )
    monkeypatch.setattr("bin_finder.providers.http.urlopen", fail)
    with pytest.raises(ProviderError) as exc:
        JsonHttpClient().get_json(
            "https://www.googleapis.com/youtube/v3/search",
            params={"key": "SECRET_API_KEY_GOES_HERE", "q": "ski"},
            provider_name="YouTube/search",
        )
    msg = str(exc.value)
    assert "SECRET_API_KEY_GOES_HERE" not in msg
    assert "secret.test" not in msg
    assert msg == f"YouTube/search: HTTP {status}; reason=" + (
        "unclassified" if expected == "unclassified" else
        next(k for k, v in {
            "accessNotConfigured": "api-not-enabled",
            "keyInvalid": "invalid-api-key",
            "quotaExceeded": "quota-exceeded",
            "invalidSearchFilter": "invalid-search-filter",
            "API_KEY_SERVICE_BLOCKED": "api-key-service-blocked",
            "PERMISSION_DENIED": "permission-denied",
        }.items() if v == expected)
    )
    assert _safe_youtube_error_code(exc.value) == f"search-http-{status}-{expected}"


def test_realistic_failed_search_returns_exact_safe_code_and_no_results():
    fake = FailHttp(ProviderError(
        "YouTube/search: HTTP 403; reason=accessNotConfigured"
    ))
    provider = YouTubeProvider("secret-not-for-logs", http=fake)
    result = discover_youtube_for_shot(
        shot(), provider, approve_youtube_api_search=True,
        max_queries=1,
    )
    assert result.status == "provider-error-no-references"
    assert result.search_attempts == 1
    assert result.error_codes == ("search-http-403-api-not-enabled",)
    assert result.hits == ()
    assert result.audiovisual_downloads == 0
    assert "secret-not-for-logs" not in repr(result)


def test_videos_details_failure_has_distinct_stage():
    class DetailFail:
        def get_json(self, base_url, *, params=None, **kw):
            if base_url.endswith("/search"):
                return {"items": [{"id": {"videoId": "AbCdefG1234"}}]}
            raise ProviderError("YouTube/details: HTTP 403; reason=quotaExceeded")
    r = discover_youtube_for_shot(
        shot(), YouTubeProvider("secret", http=DetailFail()),
        approve_youtube_api_search=True, max_queries=1,
    )
    assert r.error_codes == ("details-http-403-quota-exceeded",)
    assert r.status == "provider-error-no-references"


@pytest.mark.parametrize("error,code", [
    (ProviderError("YouTube: HTTP 403"), "http-403"),
    (ProviderError("YouTube/search: hết thời gian chờ"), "search-timeout"),
    (ProviderError("YouTube/search: không thể kết nối mạng"),
     "search-network-unreachable"),
    (ProviderError("YouTube/search: HTTP 403; reason=STOLEN_SECRET"),
     "search-http-403-unclassified"),
    (ProviderError("private-url?key=SECRET"), "provider-error"),
    (RuntimeError("raw private provider detail"), "provider-error"),
])
def test_unknown_upstream_error_cannot_leak_into_public_report(error, code):
    assert _safe_youtube_error_code(error) == code


def test_unapproved_youtube_search_remains_zero_requests_after_diagnostics():
    fake = FailHttp(ProviderError("YouTube/search: HTTP 403; reason=quotaExceeded"))
    result = discover_youtube_for_shot(
        shot(), YouTubeProvider("secret", http=fake)
    )
    assert result.search_attempts == 0
    assert result.error_codes == ()
    assert fake.calls == []


def test_cli_dry_run_still_safe_after_diagnostic_addition(tmp_path, capsys):
    assert main(["--plan-json", str(tmp_path / "never-read.json")]) == 0
    output = capsys.readouterr().out
    assert "BFS06_STATUS: approval-required" in output
    assert "BFS06_SEARCH_ATTEMPTS: 0" in output
    assert "BFS06_AUDIOVISUAL_DOWNLOADS: 0" in output
