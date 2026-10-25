"""Offline BF-S02 CLI tests; no live API, private files or media download."""
from __future__ import annotations

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderError, ProviderSearchResult, ProviderStatus
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.slot_search_smoke import (
    _safe_label, main, synthetic_example,
)


class FakeProvider:
    key = "pexels"
    display_name = "Synthetic Pexels"

    def __init__(self):
        self.calls = []

    def status(self):
        return ProviderStatus(self.key, self.display_name, True)

    def search(self, request):
        self.calls.append(request)
        return ProviderSearchResult(
            self.key,
            [CandidateRecord(
                candidate_id=f"{request.scene_id}:pexels:mock",
                scene_id=request.scene_id,
                provider=self.key,
                source_id="pexels:mock",
                title="Sunrise boats in harbor",
                duration=12,
                score=0.0,
                rights_status="unknown",
            )],
        )


def test_synthetic_single_slot_has_three_distinct_search_angles():
    scenes, plan = synthetic_example()
    assert len(scenes) == 1
    assert len(plan.search_requests()) == 1
    assert [q.axis for q in plan.search_requests()[0].queries] == [
        "subject", "moment", "action",
    ]
    assert plan.unresolved_slot_ids() == ()


def test_cli_default_never_reads_provider_config_or_calls_api(tmp_path, capsys, monkeypatch):
    def never(*args, **kwargs):
        raise AssertionError("Provider config must not be touched offline")
    monkeypatch.setattr(ProviderRegistry, "from_config", classmethod(never))
    assert main(["--project-root", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "OFFLINE_PLAN_ONLY" in output
    assert "NO_PROVIDER_CALLS" in output
    assert "BFS02_PROVIDER_CALLS" not in output


def test_live_mode_requires_explicit_flag_and_uses_only_fake_transport(
    tmp_path, monkeypatch, capsys
):
    provider = FakeProvider()
    monkeypatch.setattr(
        ProviderRegistry,
        "from_config",
        classmethod(lambda cls, config: ProviderRegistry([provider])),
    )
    assert main([
        "--provider", "pexels", "--project-root", str(tmp_path),
        "--approve-provider-calls",
    ]) == 0
    text = capsys.readouterr().out
    assert "BFS02_PROVIDER_CALLS: 3" in text
    assert "BFS02_UNVERIFIED_CANDIDATES: 1" in text
    assert "COMPLETED_UNVERIFIED_NO_SELECTION" in text
    assert "Sunrise boats in harbor" in text
    assert len(provider.calls) == 3
    assert all(req.scene_id == "scene_001" for req in provider.calls)


def test_safe_label_strips_controls_and_truncates():
    assert _safe_label("  A  B\nsecret\r\n") == "A Bsecret"
    assert _safe_label("abc" * 100, 5) == "abcab"



def test_diagnostic_sends_exactly_one_search_when_user_approves(
    tmp_path, monkeypatch, capsys
):
    provider = FakeProvider()
    monkeypatch.setattr(
        ProviderRegistry, "from_config",
        classmethod(lambda cls, config: ProviderRegistry([provider])),
    )
    assert main(["--provider", "pexels", "--project-root", str(tmp_path),
                 "--diagnose-single-query", "--approve-provider-calls"]) == 0
    output = capsys.readouterr().out
    assert len(provider.calls) == 1
    assert provider.calls[0].query == "fishing boats harbor"
    assert provider.calls[0].limit == 1
    assert "BFS02_PROVIDER_CALLS: 1" in output
    assert "BFS02_DIAGNOSTIC_CODE: ok" in output
    assert "DIAGNOSTIC_ONLY_NO_SELECTION" in output


def test_diagnostic_opt_in_is_mandatory(tmp_path, monkeypatch, capsys):
    def never(*args, **kwargs):
        raise AssertionError("Provider config read without approval")
    monkeypatch.setattr(ProviderRegistry, "from_config", classmethod(never))
    assert main(["--diagnose-single-query", "--project-root", str(tmp_path)]) == 0
    assert "BFS02_STATUS: NO_PROVIDER_CALLS" in capsys.readouterr().out


def test_diagnostic_exposes_only_safe_http_code_not_secrets(tmp_path, monkeypatch, capsys):
    class ErrorSource(FakeProvider):
        def search(self, request):
            self.calls.append(request)
            raise ProviderError("Pexels: HTTP 403")

    provider = ErrorSource()
    monkeypatch.setattr(
        ProviderRegistry, "from_config",
        classmethod(lambda cls, config: ProviderRegistry([provider])),
    )
    assert main(["--diagnose-single-query", "--approve-provider-calls",
                 "--project-root", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "BFS02_DIAGNOSTIC_CODE: http-403" in output
    assert len(provider.calls) == 1


def test_diagnostic_redacts_unknown_exception_and_signed_urls(
    tmp_path, monkeypatch, capsys
):
    secret = "VERY_PRIVATE_USER_API_KEY"
    class ErrorSource(FakeProvider):
        def search(self, request):
            self.calls.append(request)
            raise ProviderError(
                "Pexels: HTTP 403 ?key=" + secret + " https://signed.example"
            )

    provider = ErrorSource()
    monkeypatch.setattr(
        ProviderRegistry, "from_config",
        classmethod(lambda cls, config: ProviderRegistry([provider])),
    )
    assert main(["--diagnose-single-query", "--approve-provider-calls",
                 "--project-root", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "unknown-provider-error" in output
    assert secret not in output
    assert "https://signed" not in output
    assert len(provider.calls) == 1



def test_minimal_pexels_request_uses_only_documented_basics(
    tmp_path, monkeypatch, capsys
):
    from bin_finder.provider_config import ProviderConfig
    from bin_finder.providers.http import JsonHttpClient

    monkeypatch.setattr(
        ProviderConfig, "load",
        classmethod(lambda cls, root: ProviderConfig(
            pexels_api_key="PEXELS_TEST_SECRET",
        )),
    )
    calls = []

    def fake_get(self, base_url, **kwargs):
        calls.append((base_url, kwargs))
        return {"videos": [{"id": "synthetic"}]}

    monkeypatch.setattr(JsonHttpClient, "get_json", fake_get)
    assert main(["--provider", "pexels", "--project-root", str(tmp_path),
                 "--diagnose-minimal-request", "--approve-provider-calls"]) == 0
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "https://api.pexels.com/v1/videos/search"
    assert kwargs["params"] == {"query": "nature", "per_page": 1}
    assert kwargs["headers"] == {"Authorization": "PEXELS_TEST_SECRET"}
    assert kwargs["timeout"] == 15.0
    out = capsys.readouterr().out
    assert "MINIMAL_REQUEST" in out
    assert "BFS02_PROVIDER_CALLS: 1" in out
    assert "BFS02_DIAGNOSTIC_CODE: ok" in out
    assert "PEXELS_TEST_SECRET" not in out
    assert "https://" not in out


def test_minimal_pixabay_request_uses_no_size_filters_and_redacts_key(
    tmp_path, monkeypatch, capsys
):
    from bin_finder.provider_config import ProviderConfig
    from bin_finder.providers.http import JsonHttpClient

    monkeypatch.setattr(
        ProviderConfig, "load",
        classmethod(lambda cls, root: ProviderConfig(
            pixabay_api_key="PIXABAY_TEST_SECRET",
        )),
    )
    calls = []

    def fake_get(self, base_url, **kwargs):
        calls.append((base_url, kwargs))
        return {"hits": []}

    monkeypatch.setattr(JsonHttpClient, "get_json", fake_get)
    assert main(["--provider", "pixabay", "--project-root", str(tmp_path),
                 "--diagnose-minimal-request", "--approve-provider-calls"]) == 0
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == "https://pixabay.com/api/videos/"
    assert kwargs["params"] == {
        "key": "PIXABAY_TEST_SECRET", "q": "nature", "per_page": 3,
    }
    assert kwargs["headers"] == {}
    out = capsys.readouterr().out
    assert "BFS02_PROVIDER_CALLS: 1" in out
    assert "BFS02_DIAGNOSTIC_CODE: empty" in out
    assert "PIXABAY_TEST_SECRET" not in out
    assert "https://" not in out


def test_minimal_request_is_offline_without_approval(tmp_path, monkeypatch, capsys):
    from bin_finder.provider_config import ProviderConfig

    def never(*args, **kwargs):
        raise AssertionError("Config loaded without explicit approval")

    monkeypatch.setattr(ProviderConfig, "load", classmethod(never))
    assert main(["--provider", "pixabay", "--project-root", str(tmp_path),
                 "--diagnose-minimal-request"]) == 0
    assert "BFS02_STATUS: NO_PROVIDER_CALLS" in capsys.readouterr().out


def test_minimal_request_classifies_400_without_exposing_credentials(
    tmp_path, monkeypatch, capsys
):
    from bin_finder.provider_config import ProviderConfig
    from bin_finder.providers.http import JsonHttpClient

    monkeypatch.setattr(
        ProviderConfig, "load",
        classmethod(lambda cls, root: ProviderConfig(
            pixabay_api_key="PIXABAY_SECRET_400",
        )),
    )
    calls = []

    def fake_get(self, base_url, **kwargs):
        calls.append(kwargs)
        raise ProviderError("Pixabay: HTTP 400")

    monkeypatch.setattr(JsonHttpClient, "get_json", fake_get)
    assert main(["--provider", "pixabay", "--project-root", str(tmp_path),
                 "--diagnose-minimal-request", "--approve-provider-calls"]) == 0
    output = capsys.readouterr().out
    assert len(calls) == 1
    assert "BFS02_DIAGNOSTIC_CODE: http-400" in output
    assert "PIXABAY_SECRET_400" not in output
    assert "BFS02_STATUS: DIAGNOSTIC_ONLY_NO_SELECTION" in output


def test_minimal_request_rejects_mutually_exclusive_flags(capsys):
    import pytest
    with pytest.raises(SystemExit) as exc:
        main(["--diagnose-minimal-request", "--diagnose-single-query"])
    assert exc.value.code == 2
    assert "Choose only one diagnostic mode" in capsys.readouterr().err



def test_live_pilot_reports_all_ten_fairly_retained_candidates(
    tmp_path, monkeypatch, capsys
):
    class AxisProvider(FakeProvider):
        def search(self, request):
            self.calls.append(request)
            axes = {
                "fishing boats harbor": "subject",
                "coastal harbor at dawn": "moment",
                "fishing vessels entering harbor": "action",
            }
            axis = axes[request.query]
            return ProviderSearchResult(self.key, [
                CandidateRecord(
                    candidate_id=request.scene_id + ":" + axis + str(i),
                    scene_id=request.scene_id,
                    provider=self.key,
                    source_id=axis + str(i),
                    title="Synthetic " + axis + " video " + str(i),
                    duration=8.0, score=0.0, rights_status="unknown",
                    resolution="1920x1080",
                    source_url="https://example.org/private?secret=NEVER_LOG_THIS",
                    preview_url="https://example.org/asset?token=NEVER_LOG_THIS",
                )
                for i in range(5)
            ])
    provider = AxisProvider()
    monkeypatch.setattr(
        ProviderRegistry, "from_config",
        classmethod(lambda cls, config: ProviderRegistry([provider])),
    )
    assert main([
        "--provider", "pexels", "--project-root", str(tmp_path),
        "--approve-provider-calls"
    ]) == 0
    output = capsys.readouterr().out
    lines = output.splitlines()
    assert len([x for x in lines if x.startswith("BFS02_CANDIDATE:")]) == 10
    assert "BFS02_UNIQUE_DISCOVERED: 15" in output
    assert "BFS02_TRIMMED_BY_CAP: 5" in output
    assert "BFS02_REPORT_ITEMS: 10" in output
    assert "BFS02_SELECTION_POLICY: balanced-axis-provider-review-pool" in output
    assert "BFS02_AXIS_COVERAGE: subject discovered=5 kept=4" in output
    assert "BFS02_AXIS_COVERAGE: moment discovered=5 kept=3" in output
    assert "BFS02_AXIS_COVERAGE: action discovered=5 kept=3" in output
    assert "Synthetic action video" in output
    assert "1920x1080" in output
    assert len(provider.calls) == 3
    assert "NEVER_LOG_THIS" not in output
    assert "https://" not in output
