"""BF-S02.1: synthetic fairness/coverage tests, with zero HTTP access."""
from __future__ import annotations

from collections import Counter

import pytest

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.slot_candidates import SlotCandidateSearch, SlotSearchOptions
from bin_finder.search.slot_search_smoke import synthetic_example


AXES = {
    "fishing boats harbor": "subject",
    "coastal harbor at dawn": "moment",
    "fishing vessels entering harbor": "action",
}


class AxisProvider:
    display_name = "Fake source"

    def __init__(self, key, *, shared=False, missing_axis=""):
        self.key = key
        self.shared = shared
        self.missing_axis = missing_axis
        self.calls = []

    def status(self):
        return ProviderStatus(self.key, self.display_name, True)

    def search(self, req):
        axis = AXES[req.query]
        self.calls.append((axis, req.limit))
        if axis == self.missing_axis:
            return ProviderSearchResult(self.key, [])
        ids = (["shared"] if self.shared else []) + [
            axis + "-" + str(i) for i in range(1, 6)
        ]
        return ProviderSearchResult(self.key, [
            CandidateRecord(
                candidate_id=req.scene_id + ":" + source_id,
                scene_id=req.scene_id, provider=self.key,
                source_id=source_id, title="Fake " + axis + " " + source_id,
                duration=4.0, score=0.0, rights_status="unknown",
            ) for source_id in ids[:req.limit]
        ])


def search(*providers, cap=10, per_query=5):
    scenes, plan = synthetic_example()
    run = SlotCandidateSearch(
        ProviderRegistry(list(providers))
    ).search(
        plan, scenes,
        SlotSearchOptions(
            tuple(p.key for p in providers),
            per_query_limit=per_query,
            max_candidates_per_slot=cap,
            max_calls=len(providers) * 3,
        ), approve_provider_calls=True,
    )
    return run.slot("slot1"), run


def test_single_source_ten_hit_cap_does_not_discard_action_axis():
    p = AxisProvider("pexels")
    result, run = search(p, cap=10)
    assert run.provider_calls == 3
    assert p.calls == [("subject", 5), ("moment", 5), ("action", 5)]
    assert len(result.hits) == 10
    assert result.unique_discovered == 15
    assert result.trimmed_by_cap == 5
    assert result.axis_discovered == (
        ("subject", 5), ("moment", 5), ("action", 5)
    )
    assert Counter(h.matched_axes[0] for h in result.hits) == {
        "subject": 4, "moment": 3, "action": 3
    }
    assert [h.candidate.source_id for h in result.hits[:6]] == [
        "subject-1", "moment-1", "action-1",
        "subject-2", "moment-2", "action-2",
    ]


def test_two_sources_are_balanced_without_lexical_scores():
    result, run = search(AxisProvider("pexels"), AxisProvider("pixabay"), cap=10)
    assert run.provider_calls == 6
    assert result.unique_discovered == 30
    assert result.trimmed_by_cap == 20
    assert len(result.hits) == 10
    assert Counter(h.candidate.provider for h in result.hits) == {
        "pexels": 5, "pixabay": 5
    }
    assert Counter(h.matched_axes[0] for h in result.hits) == {
        "subject": 4, "moment": 3, "action": 3
    }
    assert len({h.key for h in result.hits}) == 10
    assert result.axis_discovered == (
        ("subject", 10), ("moment", 10), ("action", 10),
    )


def test_deduped_shared_asset_retains_all_axes_after_balanced_cap():
    result, run = search(AxisProvider("pexels", shared=True), cap=4)
    assert run.provider_calls == 3
    assert result.unique_discovered == 13  # 1 shared + 4 unique per axis
    assert result.trimmed_by_cap == 9
    assert len(result.hits) == 4
    assert len({h.key for h in result.hits}) == 4
    shared = next(h for h in result.hits if h.candidate.source_id == "shared")
    assert shared.matched_axes == ("subject", "moment", "action")
    assert shared.returned_order == 0
    assert result.axis_discovered == (
        ("subject", 5), ("moment", 5), ("action", 5),
    )


def test_small_cap_still_collects_all_axes_before_selection():
    result, run = search(AxisProvider("pixabay"), cap=1)
    assert run.provider_calls == 3
    assert len(result.hits) == 1
    assert result.unique_discovered == 15
    assert result.trimmed_by_cap == 14
    assert result.axis_discovered == (
        ("subject", 5), ("moment", 5), ("action", 5),
    )


def test_no_results_for_one_axis_fills_from_others():
    result, run = search(AxisProvider("pexels", missing_axis="moment"), cap=10)
    assert run.provider_calls == 3
    assert result.unique_discovered == 10
    assert result.trimmed_by_cap == 0
    assert len(result.hits) == 10
    assert Counter(h.matched_axes[0] for h in result.hits) == {
        "subject": 5, "action": 5
    }
    assert result.axis_discovered == (
        ("subject", 5), ("moment", 0), ("action", 5),
    )
    assert [a.status for a in result.attempts] == ["ok", "empty", "ok"]


def test_deterministic_selection_and_provenance_stays_first_seen():
    providers = [AxisProvider("pexels"), AxisProvider("pixabay")]
    one, _ = search(*providers, cap=9)
    two, _ = search(*providers, cap=9)
    assert one.hits == two.hits
    assert [h.returned_order for h in one.hits] != list(range(9))
    assert len({h.key for h in one.hits}) == 9
    assert all(h.candidate.rights_status == "unknown" for h in one.hits)


def test_full_pool_when_cap_exceeds_discovered_count():
    result, _ = search(AxisProvider("pexels", shared=True), cap=30)
    assert len(result.hits) == 13
    assert result.unique_discovered == 13
    assert result.trimmed_by_cap == 0


def test_existing_review_pool_keeps_lock_with_fair_selection():
    from bin_finder.search.slot_review_pool import CandidateReviewPool
    scenes, plan = synthetic_example()
    p = AxisProvider("pexels")
    service = SlotCandidateSearch(ProviderRegistry([p]))
    options = SlotSearchOptions(("pexels",), max_candidates_per_slot=10)
    run = service.search(plan, scenes, options, approve_provider_calls=True)
    pool = CandidateReviewPool.from_plan(plan).apply_run(run)
    selected_key = run.slot("slot1").hits[2].key
    locked = pool.choose("slot1", selected_key).mark_reviewed("slot1").set_lock(
        "slot1", True
    )
    newrun = service.search(plan, scenes, options, approve_provider_calls=True)
    refreshed = locked.apply_run(newrun)
    assert refreshed.get("slot1") is locked.get("slot1")
    assert refreshed.get("slot1").selected_key == selected_key
    assert pool.get("slot1").selected_key is None
