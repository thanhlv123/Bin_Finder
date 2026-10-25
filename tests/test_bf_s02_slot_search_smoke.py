"""Offline BF-S02 CLI tests; no live API, private files or media download."""
from __future__ import annotations

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus
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
