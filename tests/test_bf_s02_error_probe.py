"""BF-S02 one-call sanitized HTTP body diagnostics (no real API traffic)."""
from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from bin_finder.search import provider_error_probe as probe


@pytest.mark.parametrize("body,expected", [
    (b"Invalid API key: THIS_IS_SECRET", "invalid-api-key-indicated"),
    (b'{"error":"API key is invalid"}', "invalid-api-key-indicated"),
    (b"Please provide an API key", "missing-api-key-indicated"),
    (b"API key not provided", "missing-api-key-indicated"),
    (b'{"error":"Missing api key"}', "missing-api-key-indicated"),
    (b"Your account has no permission", "access-denied-indicated"),
    (b"Rate limit exceeded", "rate-limit-indicated"),
    (b"Cloudflare challenge required", "edge-challenge-indicated"),
    (b'{"error":"Invalid parameter: query"}',
     "invalid-request-parameter-indicated"),
    (b"<html><body>Bad Request</body></html>", "html-error-body"),
    (b"Bad Request", "generic-bad-request"),
    (b"Unexpected body with secret token=THIS_IS_SECRET",
     "unclassified-error-body"),
    (b"", "unclassified-error-body"),
])
def test_classifier_outputs_only_fixed_hint(body, expected):
    code = probe.classify_error_body(body)
    assert code == expected
    assert "THIS_IS_SECRET" not in code
    assert "http" not in code
    assert "token=" not in code


def test_pexels_error_response_reads_only_2048_bytes_and_never_leaks_secret(
    monkeypatch, capsys
):
    events = []

    class TrackedReader(io.BytesIO):
        def read(self, n=-1):
            events.append(n)
            return super().read(n)

    def fake_open(request, timeout):
        events.append((request.full_url, timeout, request.get_header("Authorization")))
        raise HTTPError(
            url="https://api.pexels.com/v1/videos/search?key=PRIVATE_URL_VALUE",
            code=400, msg="Bad Request key=PRIVATE_HTTP_ERROR_MESSAGE",
            hdrs={}, fp=TrackedReader(b'{"error": "Invalid API key PRIVATE_BODY"}'),
        )

    monkeypatch.setattr(probe, "urlopen", fake_open)
    result = probe.probe_minimal_provider("pexels", "PRIVATE_PEXELS_KEY")
    assert result.provider_calls == 1
    assert result.status_code == "http-400"
    assert result.error_hint == "invalid-api-key-indicated"
    assert result.candidate_count == 0
    assert events[0] == (
        "https://api.pexels.com/v1/videos/search?query=nature&per_page=1",
        15.0, "PRIVATE_PEXELS_KEY",
    )
    assert events[1] == 2048
    assert "PRIVATE" not in repr(result)
    assert capsys.readouterr().out == ""


def test_pixabay_query_key_never_returned_on_http_error(monkeypatch, capsys):
    def fake_open(request, timeout):
        assert request.full_url.startswith("https://pixabay.com/api/videos/?")
        assert "key=PIXABAY_SECRET" in request.full_url
        assert "q=nature" in request.full_url
        assert "per_page=3" in request.full_url
        assert timeout == 15.0
        raise HTTPError(
            url=request.full_url, code=400, msg="Bad Request",
            hdrs={}, fp=io.BytesIO(b"Bad Request"),
        )

    monkeypatch.setattr(probe, "urlopen", fake_open)
    result = probe.probe_minimal_provider("pixabay", "PIXABAY_SECRET")
    assert result.provider_calls == 1
    assert result.status_code == "http-400"
    assert result.error_hint == "generic-bad-request"
    assert "PIXABAY_SECRET" not in repr(result)
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("provider,expected_field,min_len", [
    ("pexels", "videos", 1),
    ("pixabay", "hits", 2),
])
def test_successful_minimal_request_still_works(
    monkeypatch, provider, expected_field, min_len
):
    class FakeSuccess:
        def __init__(self):
            self.buffer = io.BytesIO(
                json.dumps({expected_field: [{"id": i} for i in range(min_len)]}).encode()
            )

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self, n=-1):
            assert n == 512 * 1024 + 1
            return self.buffer.read(n)

    events = []

    def fake_open(request, timeout):
        events.append(request)
        return FakeSuccess()

    monkeypatch.setattr(probe, "urlopen", fake_open)
    result = probe.probe_minimal_provider(provider, "TEST_KEY")
    assert result.provider_calls == 1
    assert result.status_code == "ok"
    assert result.error_hint == ""
    assert result.candidate_count == min_len
    assert len(events) == 1


def test_missing_key_or_bad_provider_never_calls_network(monkeypatch):
    def never(*args, **kwargs):
        raise AssertionError("No HTTP request expected")

    monkeypatch.setattr(probe, "urlopen", never)
    assert probe.probe_minimal_provider("pexels", "  ").provider_calls == 0
    with pytest.raises(ValueError, match="unsupported-provider"):
        probe.probe_minimal_provider("evil-provider", "key")


def test_unrecognized_body_does_not_expose_signed_link_in_result(monkeypatch):
    secret_url = "https://signed.invalid/file?token=SECRET"

    def fake_open(request, timeout):
        raise HTTPError(
            url=secret_url, code=400,
            msg="HTTP 400 " + secret_url,
            hdrs={}, fp=io.BytesIO(("Unexpected: " + secret_url).encode()),
        )

    monkeypatch.setattr(probe, "urlopen", fake_open)
    output = probe.probe_minimal_provider("pixabay", "PRIVATE")
    assert output.status_code == "http-400"
    assert output.error_hint == "unclassified-error-body"
    assert "SECRET" not in repr(output)


def test_optional_cli_requires_approval_and_redacts_body_result(
    tmp_path, monkeypatch, capsys
):
    from bin_finder.provider_config import ProviderConfig
    from bin_finder.search.slot_search_smoke import main

    monkeypatch.setattr(
        ProviderConfig, "load",
        classmethod(lambda cls, root: ProviderConfig(
            pixabay_api_key="INVISIBLE_API_KEY",
        )),
    )
    calls = []

    def fake_probe(provider, api_key):
        calls.append((provider, api_key))
        return probe.ProviderProbeResult(1, "http-400",
                                         "invalid-api-key-indicated", 0)

    monkeypatch.setattr(probe, "probe_minimal_provider", fake_probe)
    assert main(["--provider", "pixabay", "--diagnose-error-body",
                 "--project-root", str(tmp_path)]) == 0
    assert calls == []
    assert "NO_PROVIDER_CALLS" in capsys.readouterr().out

    assert main(["--provider", "pixabay", "--diagnose-error-body",
                 "--approve-provider-calls", "--project-root", str(tmp_path)]) == 0
    printed = capsys.readouterr().out
    assert calls == [("pixabay", "INVISIBLE_API_KEY")]
    assert "BFS02_PROVIDER_CALLS: 1" in printed
    assert "BFS02_DIAGNOSTIC_CODE: http-400" in printed
    assert "BFS02_SERVER_HINT: invalid-api-key-indicated" in printed
    assert "INVISIBLE_API_KEY" not in printed
    assert "https://" not in printed


def test_cli_excludes_two_diagnostic_flags(capsys):
    from bin_finder.search.slot_search_smoke import main

    with pytest.raises(SystemExit) as exc:
        main(["--diagnose-minimal-request", "--diagnose-error-body"])
    assert exc.value.code == 2
    assert "Choose only one diagnostic mode" in capsys.readouterr().err
