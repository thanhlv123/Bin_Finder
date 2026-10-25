"""BF-S02 immutable, human-controlled candidate pool.

A provider candidate is a proposal, NEVER an approved clip or rights
authorization. Manual selections are not silently replaced on refresh.
F014 final selection, ZB-03 timeline, downloads and CapCut remain untouched.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from bin_finder.search.slot_candidates import (
    CandidateHit, SearchRun, SlotSearchError, SlotSearchResult,
)
from bin_finder.search.visual_search_contract import SemanticSearchPlan


@dataclass(frozen=True)
class SlotReviewState:
    slot_id: str
    action: str
    hits: tuple[CandidateHit, ...] = ()
    selected_key: tuple[str, str] | None = None
    reviewed: bool = False
    locked: bool = False
    selection_retained_after_search: bool = False
    last_search_status: str = "not-searched"

    @property
    def review_status(self) -> str:
        if self.action != "search":
            return "editorial-action-needed"
        if self.locked:
            return "locked-layout-only"
        if self.reviewed:
            return "reviewed-layout-only"
        if self.selected_key is not None:
            return "human-selected-unverified"
        if self.hits:
            return "candidates-for-review"
        return "no-candidate-selected"


@dataclass(frozen=True)
class CandidateReviewPool:
    plan_id: str
    source_digest: str
    slots: tuple[SlotReviewState, ...]

    @classmethod
    def from_plan(cls, plan: SemanticSearchPlan) -> CandidateReviewPool:
        return cls(
            plan_id=plan.plan_id,
            source_digest=plan.source_digest,
            slots=tuple(SlotReviewState(item.slot_id, item.action)
                        for item in plan.slots),
        )

    def get(self, slot_id: str) -> SlotReviewState:
        for item in self.slots:
            if item.slot_id == slot_id:
                return item
        raise SlotSearchError("unknown-review-slot")

    def _replace(self, new: SlotReviewState) -> CandidateReviewPool:
        return replace(self, slots=tuple(
            new if old.slot_id == new.slot_id else old for old in self.slots
        ))

    def choose(self, slot_id: str, key: tuple[str, str] | None) -> CandidateReviewPool:
        item = self.get(slot_id)
        if item.locked:
            raise SlotSearchError("locked-selection")
        if item.action != "search":
            raise SlotSearchError("nonsearch-selection")
        if key is not None and (type(key) is not tuple or len(key) != 2
                                or any(not isinstance(v, str) for v in key)
                                or key not in {hit.key for hit in item.hits}):
            raise SlotSearchError("unknown-candidate")
        # An explicit choice (including re-selecting same key) revokes layout
        # review, so a further human review is necessary.
        return self._replace(replace(
            item, selected_key=key, reviewed=False,
            selection_retained_after_search=False,
        ))

    def mark_reviewed(self, slot_id: str) -> CandidateReviewPool:
        """Editorial check only, never a license or F014 final approval."""
        item = self.get(slot_id)
        if item.locked:
            raise SlotSearchError("locked-selection")
        if item.action != "search" or item.selected_key is None:
            raise SlotSearchError("candidate-required")
        return self._replace(replace(item, reviewed=True))

    def set_lock(self, slot_id: str, locked: bool) -> CandidateReviewPool:
        item = self.get(slot_id)
        if type(locked) is not bool:
            raise SlotSearchError("invalid-lock-value")
        if locked and not item.reviewed:
            raise SlotSearchError("review-required-to-lock")
        return self._replace(replace(item, locked=locked))

    def apply_run(self, run: SearchRun) -> CandidateReviewPool:
        """Only update searched slots. Retain human choices and locked slots.

        If a human-selected asset is absent in a new search result, retain it
        but mark it stale: this NEVER verifies the old URL is still usable.
        """
        if not isinstance(run, SearchRun):
            raise SlotSearchError("invalid-search-run")
        if (self.plan_id != run.plan_id or self.source_digest != run.source_digest):
            raise SlotSearchError("stale-search-run")
        updated = self
        seen: set[str] = set()
        for result in run.slots:
            if not isinstance(result, SlotSearchResult):
                raise SlotSearchError("invalid-slot-result")
            if result.slot_id in seen:
                raise SlotSearchError("duplicate-slot-result")
            seen.add(result.slot_id)
            current = updated.get(result.slot_id)
            if current.action != "search":
                raise SlotSearchError("nonsearch-has-results")
            if any(hit.slot_id != result.slot_id for hit in result.hits):
                raise SlotSearchError("cross-slot-candidate")
            if len({hit.key for hit in result.hits}) != len(result.hits):
                raise SlotSearchError("duplicate-candidate")
            if current.locked:
                # Locked records are truly untouched, including metadata.
                continue
            hits = list(result.hits)
            retained = False
            if current.selected_key is not None:
                old_selected = next(
                    (hit for hit in current.hits if hit.key == current.selected_key),
                    None,
                )
                if old_selected is None:
                    raise SlotSearchError("missing-selected-record")
                if current.selected_key in {hit.key for hit in hits}:
                    # Never silently alter title, source, or metadata for a
                    # manually selected record, even if provider changes it.
                    hits = [
                        old_selected if hit.key == current.selected_key else hit
                        for hit in hits
                    ]
                else:
                    hits.append(old_selected)
                    retained = True
            updated = updated._replace(replace(
                current, hits=tuple(hits),
                # Existing explicit review survives an unrelated search.
                # This is NOT new media or licensing approval.
                selection_retained_after_search=retained,
                last_search_status=result.status,
            ))
        return updated
