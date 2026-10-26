"""BF-S03A.1 regression: noun overlap != evidence of requested action.

Synthetic records modeled on the *metadata patterns* seen in the user-local
provider pilot. No network, downloads, keys or media frames.
"""
from dataclasses import replace

from bin_finder.models import CandidateRecord
from bin_finder.search.slot_candidates import CandidateHit, SlotSearchResult
from bin_finder.search.slot_metadata_rank import SlotMetadataRanker
from bin_finder.search.slot_search_smoke import synthetic_example


def _hit(plan, source, title, index):
    slot = plan.slots[0]
    provider = source.split(":")[0]
    return CandidateHit(
        slot_id=slot.slot_id, beat_id=slot.beat_id,
        scene_ids=slot.scene_ids, matched_axes=("subject", "action"),
        returned_order=index,
        candidate=CandidateRecord(
            candidate_id="scene_001:" + source,
            scene_id=slot.scene_ids[0], provider=provider, source_id=source,
            title=title, duration=12.0, score=0,
            resolution="1920x1080", rights_status="unknown",
        ),
    )


def test_generic_fishing_harbor_keywords_do_not_outscore_sailing_alternative():
    _, plan = synthetic_example()
    generic = _hit(
        plan, "pixabay:1104",
        "boat floating waves water sea ocean vessel marine "
        "transportation fishing pier harbor port", 0,
    )
    sailing = _hit(
        plan, "pexels:10020348",
        "fishing boat sailing in sea", 1,
    )
    result = SlotMetadataRanker().rank(
        plan, SlotSearchResult("slot1", (generic, sailing), ())
    )
    assert result.ranked[0].key == sailing.key
    by_key = {item.key: item for item in result.ranked}
    assert by_key[generic.key].evidence.action_signal == "not-described"
    assert by_key[generic.key].priority == "metadata-action-unconfirmed"
    assert "action-predicate-not-described" in by_key[generic.key].reasons
    assert by_key[sailing.key].evidence.action_signal == "related-motion-only"
    assert "related-motion-does-not-prove-target-action" in by_key[sailing.key].reasons
    assert all(item.verification_status == "metadata-only-unverified"
               for item in result.ranked)


def test_direct_entering_phrase_is_stronger_than_related_sailing_phrase():
    _, plan = synthetic_example()
    direct = _hit(
        plan, "pexels:99",
        "fishing boats entering coastal harbor at dawn", 1,
    )
    related = _hit(
        plan, "pixabay:88",
        "fishing boats sailing near coastal harbor at dawn", 0,
    )
    result = SlotMetadataRanker().rank(
        plan, SlotSearchResult("slot1", (related, direct), ())
    )
    assert result.ranked[0].key == direct.key
    assert result.ranked[0].evidence.action_signal == "direct-word"
    assert result.ranked[1].evidence.action_signal == "related-motion-only"


def test_oil_refinery_time_tags_do_not_create_action_evidence():
    _, plan = synthetic_example()
    refinery = _hit(
        plan, "pixabay:330501",
        "industrial night photography oil refinery complex blue hour "
        "cityscape factory water surface", 0,
    )
    r = SlotMetadataRanker().rank(
        plan, SlotSearchResult("slot1", (refinery,), ())
    ).ranked[0]
    assert r.evidence.action_signal == "not-described"
    assert r.priority == "metadata-limited-evidence"
    assert "subject-evidence-weak" in r.reasons
    assert "action-predicate-not-described" in r.reasons


def test_stationary_docked_boat_is_flagged_not_assumed_to_be_moving():
    _, plan = synthetic_example()
    docked = _hit(
        plan, "pexels:19637496",
        "fishing boats docked in harbor water", 0,
    )
    r = SlotMetadataRanker().rank(
        plan, SlotSearchResult("slot1", (docked,), ())
    ).ranked[0]
    assert r.evidence.action_signal == "not-described"
    assert r.evidence.motion_conflict is True
    assert "motion-vs-stationary-metadata-conflict" in r.reasons
    assert r.priority == "metadata-caution"


def test_provenance_and_provider_score_do_not_create_action_evidence():
    _, plan = synthetic_example()
    generic = _hit(
        plan, "pixabay:1104",
        "fishing vessel harbor boat water", 0,
    )
    multiaxis = replace(
        generic, matched_axes=("subject", "moment", "action"),
        candidate=replace(
            generic.candidate, score=1.0,
            rights_status="pixabay_content_license",
        ),
    )
    original = SlotMetadataRanker().rank(
        plan, SlotSearchResult("slot1", (generic,), ())
    ).ranked[0]
    changed = SlotMetadataRanker().rank(
        plan, SlotSearchResult("slot1", (multiaxis,), ())
    ).ranked[0]
    assert original.score == changed.score
    assert original.evidence.action_signal == changed.evidence.action_signal
    assert original.priority == changed.priority
