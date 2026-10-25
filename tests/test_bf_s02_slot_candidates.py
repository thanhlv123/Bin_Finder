"""BF-S02 deterministic fake-provider tests, no network or private media."""
from __future__ import annotations

from dataclasses import replace

import pytest

from bin_finder.models import CandidateRecord, SceneRecord
from bin_finder.providers.base import (
    ProviderError, ProviderSearchResult, ProviderStatus,
)
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.slot_candidates import (
    SearchRun, SlotCandidateSearch, SlotSearchError,
    SlotSearchOptions, SlotSearchResult,
)
from bin_finder.search.slot_review_pool import CandidateReviewPool
from bin_finder.search.visual_search_contract import (
    FORMAT, parse_semantic_search_plan, script_digest,
)


def _scenes():
    return tuple(
        SceneRecord(scene_id="scene_%03d" % i, order=i, english_text=s)
        for i, s in enumerate((
            "Fishing boats arrive at dawn.",
            "Workers unload nets on the pier.",
            "But the picture of the town changes.",
            "Families buy food at the morning market.",
        ), 1)
    )


def _search_slot(slot_id, beat_id, sid, source_text):
    return {
        "slot_id": slot_id, "beat_id": beat_id, "scene_ids": sid,
        "role": "develop", "action": "search",
        "evidence_type": "contextual", "entity_policy": "contextual",
        "source_text": source_text,
        "visual_brief": "Observable people and locations",
        "must_show": ["visible activity"], "must_not_show": ["talking head"],
        "required_entities": [],
        "queries": [
            {"axis": "subject", "text": "fishing harbor morning"},
            {"axis": "moment", "text": "market streets daytime"},
            {"axis": "action", "text": "people working outdoors"},
        ],
        "reuse_from_slot_id": None, "uncertainty": "",
    }


def _plan():
    scenes = _scenes()
    draft = {
        "format": FORMAT, "plan_id": "bf_s02_synthetic",
        "source_digest": script_digest(scenes),
        "beats": [
            {
                "beat_id": "b1", "scene_ids": ["scene_001", "scene_002"],
                "meaning": "Harbor and work", "anchor_text": scenes[0].english_text,
                "section_context": "Physical setting", "metaphor_note": "",
            },
            {
                "beat_id": "b2", "scene_ids": ["scene_003", "scene_004"],
                "meaning": "Daily life", "anchor_text": scenes[2].english_text,
                "section_context": "Narrative contrast",
                "metaphor_note": "Not a filmable exact phrase",
            },
        ],
        "slots": [
            _search_slot("s1", "b1", ["scene_001", "scene_002"],
                         scenes[0].english_text),
            {
                "slot_id": "s2", "beat_id": "b2", "scene_ids": ["scene_003"],
                "role": "bridge", "action": "transition",
                "evidence_type": "not_applicable", "entity_policy": "unspecified",
                "source_text": scenes[2].english_text,
                "visual_brief": "Change scene editorially",
                "must_show": [], "must_not_show": [], "required_entities": [],
                "queries": [], "reuse_from_slot_id": None, "uncertainty": "",
            },
            _search_slot("s3", "b2", ["scene_004"], scenes[3].english_text),
        ],
    }
    return scenes, parse_semantic_search_plan(draft, scenes)


def _record(request, key, name, provider):
    return CandidateRecord(
        candidate_id=request.scene_id + ":" + key,
        scene_id=request.scene_id,
        provider=provider,
        source_id=key,
        title=name,
        duration=8.0,
        score=0.0,
        rights_status="unknown",
    )


class FakeProvider:
    display_name = "Synthetic Video Source"

    def __init__(self, key, *, enabled=True, fail_axis=None):
        self.key = key
        self.enabled = enabled
        self.fail_axis = fail_axis
        self.calls = []

    def status(self):
        return ProviderStatus(self.key, self.display_name, self.enabled)

    def search(self, request):
        self.calls.append(request)
        if self.fail_axis and self.fail_axis in request.query:
            raise ProviderError("SECRET TOKEN=abc123: fake upstream exception")
        # First candidate repeats across the 3 axes; second is a distinct
        # result. The *same* source ID is deliberately returned for s1/s3.
        return ProviderSearchResult(self.key, [
            _record(request, "common_video", "Synthetic harbor footage", self.key),
            _record(request, "other_video", "Another synthetic clip", self.key),
        ])


def _service(*providers):
    return SlotCandidateSearch(ProviderRegistry(list(providers)))


def test_explicit_approval_required_before_any_provider_call():
    scenes, plan = _plan()
    provider = FakeProvider("pexels")
    with pytest.raises(SlotSearchError, match="provider-calls-not-approved"):
        _service(provider).search(plan, scenes, SlotSearchOptions(("pexels",)))
    assert provider.calls == []


def test_all_three_axes_per_slot_and_nonsearch_untouched():
    scenes, plan = _plan()
    px = FakeProvider("pexels")
    pb = FakeProvider("pixabay")
    run = _service(px, pb).search(
        plan, scenes, SlotSearchOptions(
            ("pexels", "pixabay"), max_calls=12,
        ), approve_provider_calls=True
    )
    assert run.plan_id == plan.plan_id
    assert run.source_digest == plan.source_digest
    assert run.skipped_slots == ("s2",)
    assert run.provider_calls == 12
    assert len(px.calls) == 6
    assert len(pb.calls) == 6
    assert [r.query for r in px.calls[:3]] == [
        "fishing harbor morning", "market streets daytime",
        "people working outdoors",
    ]
    assert set(r.scene_id for r in px.calls[:3]) == {"scene_001"}
    assert set(r.scene_id for r in px.calls[3:]) == {"scene_004"}
    assert all(len(result.attempts) == 6 for result in run.slots)
    assert len(run.slots) == 2
    assert len(run.slot("s1").hits) == 4
    assert len(run.slot("s3").hits) == 4
    assert run.slot("s1").status == "candidates-unverified"
    assert run.slot("s1").hits[0].matched_axes == (
        "subject", "moment", "action"
    )
    assert run.slot("s3").hits[0].matched_axes == (
        "subject", "moment", "action"
    )
    assert run.slot("s1").hits[0].key == run.slot("s3").hits[0].key
    # Same asset is separate per slot; provider CandidateRecord is never
    # altered to fake a new (possibly wrong) scene ID.
    assert run.slot("s1").hits[0].scene_ids == ("scene_001", "scene_002")
    assert run.slot("s3").hits[0].scene_ids == ("scene_004",)
    assert run.slot("s1").hits[0].candidate.scene_id == "scene_001"


def test_error_is_per_query_and_does_not_leak_credentials():
    scenes, plan = _plan()
    px = FakeProvider("pexels", fail_axis="market streets")
    pb = FakeProvider("pixabay")
    run = _service(px, pb).search(
        plan, scenes, SlotSearchOptions(("pexels", "pixabay"), max_calls=12),
        approve_provider_calls=True
    )
    assert run.provider_calls == 12
    assert sum(x.status == "provider-error"
               for r in run.slots for x in r.attempts) == 2
    assert len(run.slot("s1").hits) > 0
    assert len(run.slot("s3").hits) > 0
    assert "abc123" not in repr(run)
    assert all(a.received == 0 for r in run.slots
               for a in r.attempts if a.status == "provider-error")


def test_unconfigured_provider_never_calls_search_but_other_source_does():
    scenes, plan = _plan()
    px = FakeProvider("pexels", enabled=False)
    pb = FakeProvider("pixabay")
    run = _service(px, pb).search(
        plan, scenes, SlotSearchOptions(("pexels", "pixabay"), max_calls=12),
        approve_provider_calls=True
    )
    assert len(px.calls) == 0
    assert len(pb.calls) == 6
    assert run.provider_calls == 6
    assert any(a.status == "not-configured" for a in run.slot("s1").attempts)


def test_unknown_provider_is_reported_not_guessed_or_silently_replaced():
    scenes, plan = _plan()
    px = FakeProvider("pexels")
    run = _service(px).search(
        plan, scenes, SlotSearchOptions(("nonexistent",), max_calls=6),
        approve_provider_calls=True
    )
    assert run.provider_calls == 0
    assert run.slot("s1").status == "provider-unavailable"
    assert all(a.status == "not-configured" for a in run.slot("s1").attempts)


@pytest.mark.parametrize("bad_opts", [
    SlotSearchOptions(()),
    SlotSearchOptions(("pexels", "pexels")),
    SlotSearchOptions(("pexels",), per_query_limit=21),
    SlotSearchOptions(("pexels",), max_candidates_per_slot=0),
    SlotSearchOptions(("pexels",), max_calls=19),
    SlotSearchOptions(("pexels",), orientation="upside-down"),
])
def test_bad_settings_fail_before_first_request(bad_opts):
    scenes, plan = _plan()
    px = FakeProvider("pexels")
    with pytest.raises(SlotSearchError):
        _service(px).search(
            plan, scenes, bad_opts, approve_provider_calls=True
        )
    assert px.calls == []


def test_call_budget_rejected_without_partial_network_requests():
    scenes, plan = _plan()
    px = FakeProvider("pexels")
    with pytest.raises(SlotSearchError, match="search-budget-exceeded"):
        _service(px).search(
            plan, scenes, SlotSearchOptions(("pexels",), max_calls=3),
            approve_provider_calls=True
        )
    assert px.calls == []


def test_wrong_script_refused_before_provider_calls():
    scenes, plan = _plan()
    modified = list(scenes)
    modified[1] = replace(modified[1], english_text="Replaced narration.")
    px = FakeProvider("pexels")
    with pytest.raises(ValueError, match="stale-script"):
        _service(px).search(
            plan, modified, SlotSearchOptions(("pexels",)),
            approve_provider_calls=True
        )
    assert px.calls == []


def test_no_auto_choice_and_manual_lock_preserved_across_refreshes():
    scenes, plan = _plan()
    px = FakeProvider("pexels")
    svc = _service(px)
    run = svc.search(plan, scenes, SlotSearchOptions(("pexels",)),
                     approve_provider_calls=True)
    pool = CandidateReviewPool.from_plan(plan).apply_run(run)
    one = pool.get("s1")
    assert one.selected_key is None
    assert one.review_status == "candidates-for-review"
    assert pool.get("s2").review_status == "editorial-action-needed"
    selected = pool.choose("s1", one.hits[0].key)
    assert selected.get("s1").review_status == "human-selected-unverified"
    checked = selected.mark_reviewed("s1")
    locked = checked.set_lock("s1", True)
    assert locked.get("s1").review_status == "locked-layout-only"
    replacement = svc.search(
        plan, scenes, SlotSearchOptions(("pexels",)),
        approve_provider_calls=True
    )
    refreshed = locked.apply_run(replacement)
    assert refreshed.get("s1") is locked.get("s1")
    assert refreshed.get("s3").hits
    assert refreshed.get("s2") is locked.get("s2")
    assert pool.get("s1").selected_key is None


def test_human_selection_survives_disappearance_and_is_flagged_stale():
    scenes, plan = _plan()
    run = _service(FakeProvider("pexels")).search(
        plan, scenes, SlotSearchOptions(("pexels",)),
        approve_provider_calls=True
    )
    selected = CandidateReviewPool.from_plan(plan).apply_run(run)
    chosen = selected.get("s1").hits[0]
    selected = selected.choose("s1", chosen.key).mark_reviewed("s1")
    emptied = SearchRun(plan.plan_id, plan.source_digest, (
        SlotSearchResult("s1", (), ()),
    ), (), 0)
    refreshed = selected.apply_run(emptied)
    slot = refreshed.get("s1")
    assert slot.selected_key == chosen.key
    assert slot.hits == (chosen,)
    assert slot.selection_retained_after_search is True
    assert slot.reviewed is True  # layout-only, still needs availability check
    assert refreshed.get("s3") == selected.get("s3")


def test_unreviewed_candidate_cannot_be_locked_or_crossed_into_wrong_slot():
    scenes, plan = _plan()
    run = _service(FakeProvider("pexels")).search(
        plan, scenes, SlotSearchOptions(("pexels",)),
        approve_provider_calls=True
    )
    pool = CandidateReviewPool.from_plan(plan).apply_run(run)
    with pytest.raises(SlotSearchError, match="review-required-to-lock"):
        pool.set_lock("s1", True)
    with pytest.raises(SlotSearchError, match="unknown-candidate"):
        pool.choose("s1", ("pixabay", "missing"))
    with pytest.raises(SlotSearchError, match="nonsearch-selection"):
        pool.choose("s2", ("pexels", "common_video"))
    with pytest.raises(SlotSearchError, match="stale-search-run"):
        pool.apply_run(replace(run, source_digest="different"))
    forged = replace(run, slots=(
        replace(run.slot("s1"), hits=run.slot("s3").hits),
    ))
    with pytest.raises(SlotSearchError, match="cross-slot-candidate"):
        pool.apply_run(forged)



def test_provider_contract_error_is_not_misreported_as_no_matching_footage():
    scenes, plan = _plan()

    class MalformedProvider(FakeProvider):
        def search(self, request):
            self.calls.append(request)
            return ProviderSearchResult("wrong-provider", [])

    fake = MalformedProvider("pexels")
    run = _service(fake).search(
        plan, scenes, SlotSearchOptions(("pexels",)),
        approve_provider_calls=True
    )
    assert run.slot("s1").hits == ()
    assert run.slot("s1").status == "technical-error-no-candidates"
    assert all(a.status == "invalid-provider-result"
               for a in run.slot("s1").attempts)
    assert len(fake.calls) == 6


def test_real_empty_search_is_distinct_from_technical_failure():
    scenes, plan = _plan()

    class EmptyProvider(FakeProvider):
        def search(self, request):
            self.calls.append(request)
            return ProviderSearchResult(self.key, [])

    fake = EmptyProvider("pexels")
    run = _service(fake).search(
        plan, scenes, SlotSearchOptions(("pexels",)),
        approve_provider_calls=True
    )
    assert run.slot("s1").status == "no-candidates-found"
    assert all(a.status == "empty" for a in run.slot("s1").attempts)
