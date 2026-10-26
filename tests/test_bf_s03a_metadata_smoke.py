"""BF-S03A offline-first smoke tests, fake providers only."""
from __future__ import annotations

from bin_finder.models import CandidateRecord
from bin_finder.provider_config import ProviderConfig
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.slot_metadata_smoke import main, _safe_id


class Source:
    display_name = "Test fake provider"

    def __init__(self, key):
        self.key = key
        self.calls = []

    def status(self):
        return ProviderStatus(self.key, self.display_name, True)

    def search(self, request):
        self.calls.append(request)
        return ProviderSearchResult(self.key, [
            CandidateRecord(
                candidate_id="test:" + self.key + ":" + str(len(self.calls)),
                scene_id=request.scene_id,
                provider=self.key,
                source_id=self.key + ":" + str(len(self.calls)),
                title="Fishing boat sailing into harbor at dawn on water",
                duration=10.0, score=0,
                resolution="1920x1080", rights_status="unknown",
                source_url="https://secret.example/?key=DONT_SHOW_THIS",
            )
        ])


def test_default_offline_never_loads_api_config_or_calls_providers(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise AssertionError("No private provider configuration in offline mode")

    monkeypatch.setattr(ProviderConfig, "load", classmethod(fail))
    assert main([]) == 0
    stdout = capsys.readouterr().out
    assert "BFS03A_MODE: OFFLINE_SYNTHETIC_NO_PROVIDER_CALLS" in stdout
    assert "BFS03A_PROVIDER_CALLS: 0" in stdout
    assert "BFS03A_FRAME_OR_LICENSING_VERIFIED: False" in stdout
    assert "BFS03A_NO_DOWNLOAD_OR_VISION: True" in stdout
    assert stdout.count("BFS03A_RANK:") == 5
    assert "METADATA_ONLY_HUMAN_REVIEW_REQUIRED" in stdout


def test_live_two_provider_option_needs_both_flags(capsys):
    import pytest
    for arg in ("--live-providers", "--approve-provider-calls"):
        with pytest.raises(SystemExit) as err:
            main([arg])
        assert err.value.code == 2
        assert "requires both opt-in flags" in capsys.readouterr().err


def test_live_fake_provider_search_calls_six_and_never_logs_signed_url(
    tmp_path, capsys, monkeypatch,
):
    pexels = Source("pexels")
    pixabay = Source("pixabay")
    monkeypatch.setattr(
        ProviderConfig, "load",
        classmethod(lambda cls, root: ProviderConfig(
            pexels_api_key="PRIVATE_PEXELS_KEY",
            pixabay_api_key="PRIVATE_PIXABAY_KEY",
        )),
    )
    monkeypatch.setattr(
        ProviderRegistry, "from_config",
        classmethod(lambda cls, config: ProviderRegistry([pexels, pixabay])),
    )
    assert main([
        "--live-providers", "--approve-provider-calls",
        "--project-root", str(tmp_path),
    ]) == 0
    text = capsys.readouterr().out
    assert len(pexels.calls) == len(pixabay.calls) == 3
    assert "BFS03A_PROVIDER_CALLS: 6" in text
    assert "BFS03A_INPUT_CANDIDATES: 6" in text
    assert text.count("BFS03A_RANK:") == 6
    assert "BFS03A_TOP5_REVIEW:" in text
    assert "PRIVATE_PEXELS_KEY" not in text
    assert "PRIVATE_PIXABAY_KEY" not in text
    assert "DONT_SHOW_THIS" not in text
    assert "https://" not in text


def test_source_ids_allowlist_does_not_print_untrusted_payload():
    assert _safe_id("pixabay:123456") == "pixabay:123456"
    assert _safe_id("pexels:678") == "pexels:678"
    assert _safe_id("pixabay:123?key=PRIVATE") == "redacted-identifier"
    assert _safe_id("https://signed.example/?key=PRIVATE") == "redacted-identifier"
