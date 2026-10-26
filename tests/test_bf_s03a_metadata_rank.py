"""BF-S03A metadata ranking: synthetic no-network travel/history/economy tests."""
from __future__ import annotations

from dataclasses import replace

import pytest

from bin_finder.models import CandidateRecord
from bin_finder.search.slot_candidates import CandidateHit, SlotSearchResult
from bin_finder.search.slot_metadata_rank import (
    MetadataRankSettings, MetadataRankingError, SlotMetadataRanker,
)
from bin_finder.search.slot_search_smoke import synthetic_example
from bin_finder.search.visual_search_contract import VisualQuery


def _scenario(
    subject="fishing boats harbor",
    moment="coastal harbor at dawn",
    action="fishing vessels entering harbor",
    must_show=("boats", "water", "harbor"),
    must_not_show=("talking head", "indoor studio"),
    required_entities=(),
):
    _, plan = synthetic_example()
    s = plan.slots[0]
    updated = replace(s, queries=(
        VisualQuery("subject", subject), VisualQuery("moment", moment),
        VisualQuery("action", action),
    ), must_show=must_show, must_not_show=must_not_show,
        required_entities=required_entities)
    return replace(plan, slots=(updated,))


def _hit(plan, identifier, title, *, provider="pexels",
         resolution="1920x1080", axes=("subject",), order=0,
         description="", rights="unknown", url=""):
    s = plan.slots[0]
    candidate = CandidateRecord(
        candidate_id=s.scene_ids[0] + ":" + identifier,
        scene_id=s.scene_ids[0], provider=provider,
        source_id=provider + ":" + identifier,
        title=title, duration=12.0, score=0.99,
        rights_status=rights, resolution=resolution,
        description=description,
        source_url=url,
    )
    return CandidateHit(
        slot_id=s.slot_id, beat_id=s.beat_id, scene_ids=s.scene_ids,
        candidate=candidate, matched_axes=axes, returned_order=order,
    )


def _rank(plan, *hits):
    return SlotMetadataRanker().rank(
        plan, SlotSearchResult(plan.slots[0].slot_id, tuple(hits), ())
    )


def test_travel_harbor_movement_is_prioritized_over_moored_boats():
    plan = _scenario()
    moving = _hit(plan, "moving",
                  "Fishing boat sailing toward coastal harbor at dawn on water",
                  order=2, axes=("action",))
    moored = _hit(plan, "moored",
                  "Fishing boats docked in harbor at dawn on water",
                  order=0, axes=("subject", "action"))
    refinery = _hit(plan, "refinery",
                    "Industrial oil refinery blue hour night skyline",
                    order=1, axes=("moment",))
    result = _rank(plan, moored, refinery, moving)
    assert [r.key for r in result.ranked] == [
        moving.key, moored.key, refinery.key
    ]
    assert result.ranked[0].verification_status == "metadata-only-unverified"
    assert result.ranked[0].priority == "metadata-promising-for-review"
    assert result.ranked[1].priority == "metadata-caution"
    assert "motion-vs-stationary-metadata-conflict" in result.ranked[1].reasons
    assert result.status == "metadata-priority-only"


def test_history_havana_old_street_metadata_ranks_above_modern_highway():
    plan = _scenario(
        subject="Havana classic cars colonial streets",
        moment="Havana 1950s historical street",
        action="classic cars driving colonial street",
        must_show=("Havana", "classic cars", "colonial street"),
        must_not_show=("modern highway", "talking head"),
        required_entities=("Havana",),
    )
    archival = _hit(
        plan, "classic",
        "1950s Havana classic cars driving through colonial street",
        resolution="3840x2160",
    )
    generic = _hit(
        plan, "modern",
        "Classic cars on modern highway outside city",
        resolution="3840x2160",
    )
    ranked = _rank(plan, generic, archival)
    assert ranked.ranked[0].key == archival.key
    assert "required-entity-not-confirmed-in-metadata" in ranked.ranked[1].reasons
    assert ranked.ranked[1].priority == "metadata-caution"
    assert "must-not-show-phrase-in-metadata" in ranked.ranked[1].reasons


def test_economy_shortage_and_stocked_supermarket_are_distinguished():
    plan = _scenario(
        subject="supermarket grocery shelves shortages",
        moment="economic inflation food crisis",
        action="customers searching empty supermarket shelves",
        must_show=("supermarket shelves", "empty shelves"),
        must_not_show=("fully stocked shelves",),
        required_entities=(),
    )
    shortage = _hit(
        plan, "shortage",
        "Empty supermarket shelves amid food shortages inflation crisis",
        description="Customers searching for food",
    )
    stocked = _hit(
        plan, "stocked",
        "Fully stocked shelves at supermarket grocery store with customers",
    )
    output = _rank(plan, stocked, shortage)
    assert output.ranked[0].key == shortage.key
    assert output.ranked[1].evidence.excluded_phrase is True
    assert output.ranked[1].priority == "metadata-caution"


def test_multiaxis_provenance_does_not_auto_inflate_score():
    plan = _scenario()
    one = _hit(plan, "same", "Fishing boats in harbor",
               axes=("subject",), order=0)
    many = replace(one, matched_axes=("subject", "moment", "action"))
    first = _rank(plan, one).ranked[0]
    second = _rank(plan, many).ranked[0]
    assert first.score == second.score
    assert first.reasons == second.reasons


def test_source_provider_score_and_licensing_label_never_increase_priority():
    plan = _scenario()
    base = _hit(plan, "a", "Fishing boat on harbor", rights="unknown")
    different = replace(
        base,
        candidate=replace(
            base.candidate, score=1.0, rights_status="pexels_license",
        ),
    )
    assert _rank(plan, base).ranked[0].score == _rank(plan, different).ranked[0].score
    assert _rank(plan, different).ranked[0].verification_status == "metadata-only-unverified"


def test_4k_portrait_gets_no_full_landscape_quality_bonus():
    plan = _scenario()
    landscape = _hit(plan, "landscape", "Fishing boats harbor",
                     resolution="3840x2160")
    portrait = _hit(plan, "portrait", "Fishing boats harbor",
                    resolution="2160x3840")
    scores = _rank(plan, landscape, portrait).ranked
    assert scores[0].key == landscape.key
    assert scores[0].evidence.quality_points == 10
    assert scores[1].evidence.quality_points == 4
    assert "video-orientation-review" in scores[1].reasons


def test_missing_resolution_is_uncertainty_not_automatic_disqualification():
    plan = _scenario()
    unknown = _hit(plan, "unknown",
                   "Fishing boat sailing entering harbor water at dawn",
                   resolution="")
    result = _rank(plan, unknown).ranked[0]
    assert result.evidence.quality_points == 0
    assert "resolution-unknown" in result.reasons
    assert result.score > 0


def test_missing_subject_with_time_keywords_is_not_promising():
    plan = _scenario()
    only_dawn = _hit(plan, "dawn", "Sunrise at beach during early dawn")
    result = _rank(plan, only_dawn).ranked[0]
    assert result.evidence.subject == 0
    assert result.priority == "metadata-limited-evidence"
    assert "subject-evidence-weak" in result.reasons


def test_untrusted_source_urls_and_metadata_never_enter_explanations():
    plan = _scenario()
    secret = "VERY_SECRET_SIGNED_LINK_VALUE"
    item = _hit(plan, "no-leak",
                "Fishing boats harbor",
                url="https://example.org/?key=" + secret)
    c = replace(item.candidate, source_metadata={"key": secret})
    scored = _rank(plan, replace(item, candidate=c)).ranked[0]
    assert secret not in repr(scored.reasons)
    assert "https://" not in repr(scored.reasons)


def test_empty_slot_returns_empty_status_without_fabricating_candidates():
    plan = _scenario()
    output = _rank(plan)
    assert output.status == "metadata-priority-only"
    assert output.ranked == ()
    assert output.top_for_review() == ()


def test_equal_scores_stable_first_seen_order_no_mutation():
    plan = _scenario()
    first = _hit(plan, "first", "Fishing boats", order=1)
    second = _hit(plan, "second", "Fishing boats", order=0)
    original = (first, second)
    output = _rank(plan, *original)
    assert [r.key for r in output.ranked] == [second.key, first.key]
    assert original == (first, second)


@pytest.mark.parametrize("setting", [
    MetadataRankSettings(preferred_orientation="square"),
    MetadataRankSettings(preferred_min_height=0),
    MetadataRankSettings(preferred_min_width=99999),
])
def test_invalid_settings_rejected_with_fixed_reason(setting):
    with pytest.raises(MetadataRankingError, match="invalid-rank-settings"):
        SlotMetadataRanker(setting)


def test_invalid_slot_is_rejected_before_any_ranking():
    plan = _scenario()
    with pytest.raises(MetadataRankingError, match="invalid-search-slot"):
        SlotMetadataRanker().rank(plan, SlotSearchResult("unknown", (), ()))


def test_cross_slot_and_duplicate_candidate_rejected():
    plan = _scenario()
    hit = _hit(plan, "one", "Fishing boats harbor")
    with pytest.raises(MetadataRankingError, match="invalid-candidate-provenance"):
        _rank(plan, replace(hit, slot_id="other-slot"))
    with pytest.raises(MetadataRankingError, match="invalid-candidate-set"):
        _rank(plan, hit, hit)


def test_review_limit_has_small_bound():
    plan = _scenario()
    result = _rank(plan, _hit(plan, "one", "Fishing boats harbor"))
    assert len(result.top_for_review(1)) == 1
    with pytest.raises(MetadataRankingError, match="invalid-review-limit"):
        result.top_for_review(0)
