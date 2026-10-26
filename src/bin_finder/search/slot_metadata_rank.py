"""BF-S03A metadata-only, evidence-aware ranking of BF-S02 visual-slot candidates.

No network, file access, provider calls, media downloads, local VLM calls,
license approval, automatic selection, or production GUI/timeline changes.

Scores are HEURISTIC priorities for human/video review, NOT verification of
video content. Missing words are weak evidence, not proof of visual absence.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from bin_finder.models import CandidateRecord
from bin_finder.search.slot_candidates import CandidateHit, SlotSearchResult
from bin_finder.search.visual_search_contract import SemanticSearchPlan, VisualSlot


class MetadataRankingError(ValueError):
    """Stable fixed code; never interpolate arbitrary user/provider text."""


_AXES = ("subject", "moment", "action")
_STOPWORDS = frozenset({
    "a", "an", "the", "at", "of", "in", "on", "for", "by", "to", "from",
    "and", "or", "with", "into", "near", "through", "there", "its",
    "this", "that", "is", "are", "was", "were", "as", "during",
    "video", "footage", "clip", "photo", "image", "scene",
})
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_RESOLUTION = re.compile(r"^(\d{2,5})\s*[xX×]\s*(\d{2,5})$")
_MOTION = frozenset({
    "enter", "arrive", "approach", "sail", "move", "moving",
    "leave", "depart", "drive", "walk", "run", "travel", "head",
})
_STILL = frozenset({
    "dock", "moor", "anchor", "park", "stationary", "idle",
})
# BF-S03A.1: tiny, explicit action vocabulary for evidence *caution*.
# These are not AI semantics. Related movement does not prove "entering".
_ACTION_PREDICATES = frozenset({
    "enter", "arrive", "approach", "sail", "move", "leave", "depart",
    "drive", "walk", "run", "travel", "head", "search", "repair",
    "unload", "load", "build", "sell", "buy", "deliver", "cross",
    "march", "protest", "open", "close", "wait", "work", "cook",
})
_ARRIVAL_PREDICATES = frozenset({"enter", "arrive", "approach"})
_RELATED_MOVEMENT = frozenset({
    "sail", "move", "head", "travel", "approach", "arrive", "enter",
    "drive",
})


def _lemma(word: str) -> str:
    word = word.casefold()
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        root = word[:-3]
        return root + "e" if root in {"mov", "driv", "leav", "arriv"} else root
    if len(word) > 4 and word.endswith("ed"):
        root = word[:-2]
        return root[:-1] if root.endswith(root[-1:] * 2) else root
    if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(
        w for raw in _WORD.findall(text[:2200].casefold())
        if (w := _lemma(raw)) not in _STOPWORDS and len(w) >= 3
    )


def _coverage(query: str, text_words: set[str]) -> float:
    words = set(_tokens(query))
    return len(words & text_words) / len(words) if words else 0.0


def _phrase_visible(phrase: str, text_words: Sequence[str]) -> bool:
    words = _tokens(phrase)
    if not words:
        return False
    n = len(words)
    return any(tuple(text_words[i:i + n]) == words
               for i in range(len(text_words) - n + 1))


def _dimensions(candidate: CandidateRecord) -> tuple[int, int] | None:
    m = _RESOLUTION.fullmatch(candidate.resolution.strip())
    if not m:
        return None
    width, height = map(int, m.groups())
    if width < 1 or height < 1:
        return None
    return width, height


@dataclass(frozen=True)
class MetadataRankSettings:
    """Landscape video is a preview preference, NOT an eligibility gate."""
    preferred_orientation: str = "landscape"
    preferred_min_width: int = 1280
    preferred_min_height: int = 720

    def validate(self) -> None:
        if (self.preferred_orientation not in {"landscape", "portrait", "any"}
                or type(self.preferred_min_width) is not int
                or type(self.preferred_min_height) is not int
                or not 1 <= self.preferred_min_width <= 8192
                or not 1 <= self.preferred_min_height <= 8192):
            raise MetadataRankingError("invalid-rank-settings")


@dataclass(frozen=True)
class MetadataEvidence:
    """Numeric values express lexical coverage, not model probability."""
    subject: float
    moment: float
    action: float
    must_show: float
    required_entities: float
    quality_points: int
    motion_conflict: bool
    excluded_phrase: bool
    action_signal: str = "not-applicable"


@dataclass(frozen=True)
class RankedSlotCandidate:
    hit: CandidateHit
    score: int
    evidence: MetadataEvidence
    reasons: tuple[str, ...]
    priority: str
    verification_status: str = "metadata-only-unverified"

    @property
    def key(self) -> tuple[str, str]:
        return self.hit.key


@dataclass(frozen=True)
class MetadataRankResult:
    slot_id: str
    ranked: tuple[RankedSlotCandidate, ...]
    status: str = "metadata-priority-only"

    def top_for_review(self, limit: int = 5) -> tuple[RankedSlotCandidate, ...]:
        if type(limit) is not int or not 1 <= limit <= 60:
            raise MetadataRankingError("invalid-review-limit")
        return self.ranked[:limit]


def _quality_points(candidate: CandidateRecord, settings: MetadataRankSettings) -> tuple[int, str]:
    resolution = _dimensions(candidate)
    if resolution is None:
        return 0, "resolution-unknown"
    width, height = resolution
    orientation = "landscape" if width > height else ("portrait" if height > width else "square")
    orientation_ok = settings.preferred_orientation == "any" or orientation == settings.preferred_orientation
    size_ok = width >= settings.preferred_min_width and height >= settings.preferred_min_height
    if orientation_ok and size_ok:
        return 10, "video-format-preferred"
    if size_ok:
        return 4, "video-orientation-review"
    return 0, "video-resolution-review"


def _rank_one(
    slot: VisualSlot, hit: CandidateHit, settings: MetadataRankSettings,
) -> RankedSlotCandidate:
    candidate = hit.candidate
    # Provider descriptive text is UNTRUSTED and can be inaccurate; do not
    # parse arbitrary source_metadata or any URL into lexical evidence.
    metadata_words = _tokens(candidate.title + " " + candidate.description[:1600])
    wordset = set(metadata_words)
    q = {item.axis: item.text for item in slot.queries}
    subject = _coverage(q["subject"], wordset)
    moment = _coverage(q["moment"], wordset)
    action = _coverage(q["action"], wordset)

    must_show = (
        sum(_coverage(term, wordset) for term in slot.must_show)
        / len(slot.must_show)
        if slot.must_show else 0.0
    )
    required = (
        sum(_coverage(term, wordset) for term in slot.required_entities)
        / len(slot.required_entities)
        if slot.required_entities else 1.0
    )
    excluded = any(_phrase_visible(term, metadata_words) for term in slot.must_not_show)
    motion_required = bool(set(_tokens(q["action"])) & _MOTION)
    motion_indicated = bool(wordset & _MOTION)
    stationary_indicated = bool(wordset & _STILL)
    motion_conflict = motion_required and stationary_indicated and not motion_indicated
    # Query nouns appearing in provider tags do NOT establish that an
    # observable action occurs. Determine action-predicate evidence separately.
    action_predicates = set(_tokens(q["action"])) & _ACTION_PREDICATES
    if not action_predicates:
        action_signal = "not-applicable"
    elif action_predicates & wordset:
        action_signal = "direct-word"
    elif (action_predicates & _ARRIVAL_PREDICATES
          and wordset & _RELATED_MOVEMENT):
        action_signal = "related-motion-only"
    else:
        action_signal = "not-described"
    quality, quality_reason = _quality_points(candidate, settings)

    # Max: 38 + 12 + 20 + 20 + 10 = 100. Required-entity uncertainty
    # and explicit conflicting metadata apply cautious penalties. Never score
    # source/provider IDs, original API score or matched_axes as relevancy.
    score = round(38 * subject + 12 * moment + 20 * action
                  + 20 * must_show + quality)
    if slot.required_entities and required < 1.0:
        score -= round(12 * (1.0 - required))
    if excluded:
        score -= 32
    if motion_conflict:
        score -= 24
    # When an action predicate is identifiable, generic search-hit nouns
    # (e.g. "fishing vessel harbor") must not create confident action scores.
    if action_signal == "not-described":
        score -= 40
    elif action_signal == "related-motion-only":
        score += 8
    elif action_signal == "direct-word":
        score += 12
    score = max(0, min(100, score))

    reasons: list[str] = [quality_reason, "unverified-provider-metadata"]
    if subject < 0.5:
        reasons.append("subject-evidence-weak")
    if moment < 0.5:
        reasons.append("moment-evidence-weak")
    if action < 0.5:
        reasons.append("action-evidence-weak")
    if slot.must_show and must_show < 1:
        reasons.append("must-show-not-confirmed-in-metadata")
    if slot.required_entities and required < 1:
        reasons.append("required-entity-not-confirmed-in-metadata")
    if excluded:
        reasons.append("must-not-show-phrase-in-metadata")
    if motion_conflict:
        reasons.append("motion-vs-stationary-metadata-conflict")
    if action_signal == "not-described":
        reasons.append("action-predicate-not-described")
    elif action_signal == "related-motion-only":
        reasons.append("related-motion-does-not-prove-target-action")

    # "promising" is always a metadata review priority, never visual
    # verification, licensing clearance, or automatic candidate approval.
    if excluded or motion_conflict:
        priority = "metadata-caution"
    elif subject < 0.5:
        priority = "metadata-limited-evidence"
    elif action_signal == "not-described":
        priority = "metadata-action-unconfirmed"
    elif action >= 0.5 or moment >= 0.5:
        priority = "metadata-promising-for-review"
    else:
        priority = "metadata-limited-evidence"

    return RankedSlotCandidate(
        hit=hit, score=score,
        evidence=MetadataEvidence(
            subject=round(subject, 4), moment=round(moment, 4),
            action=round(action, 4), must_show=round(must_show, 4),
            required_entities=round(required, 4), quality_points=quality,
            motion_conflict=motion_conflict, excluded_phrase=excluded,
            action_signal=action_signal,
        ),
        reasons=tuple(reasons), priority=priority,
    )


class SlotMetadataRanker:
    """Read-only ordering of an already capped BF-S02 slot review pool."""

    def __init__(self, settings: MetadataRankSettings | None = None) -> None:
        self.settings = settings or MetadataRankSettings()
        self.settings.validate()

    def rank(
        self, plan: SemanticSearchPlan, slot_result: SlotSearchResult,
    ) -> MetadataRankResult:
        if not isinstance(plan, SemanticSearchPlan) or not isinstance(
            slot_result, SlotSearchResult
        ):
            raise MetadataRankingError("invalid-ranking-input")
        matches = [slot for slot in plan.slots if slot.slot_id == slot_result.slot_id]
        if len(matches) != 1 or matches[0].action != "search":
            raise MetadataRankingError("invalid-search-slot")
        slot = matches[0]
        if (len(slot_result.hits) > 60
                or any(not isinstance(hit, CandidateHit) for hit in slot_result.hits)):
            raise MetadataRankingError("invalid-candidate-set")
        if len({hit.key for hit in slot_result.hits}) != len(slot_result.hits):
            raise MetadataRankingError("invalid-candidate-set")
        for hit in slot_result.hits:
            if (hit.candidate is None
                    or hit.slot_id != slot.slot_id
                    or hit.beat_id != slot.beat_id
                    or hit.scene_ids != slot.scene_ids
                    or hit.candidate.scene_id != slot.scene_ids[0]
                    or hit.candidate.provider not in {"pexels", "pixabay", "local", "youtube", "storyblocks"}
                    or not isinstance(hit.candidate.title, str)
                    or not isinstance(hit.candidate.description, str)
                    or not isinstance(hit.candidate.resolution, str)):
                raise MetadataRankingError("invalid-candidate-provenance")
        scored = [_rank_one(slot, hit, self.settings) for hit in slot_result.hits]
        scored.sort(key=lambda item: (-item.score, item.hit.returned_order,
                                     item.hit.candidate.provider, item.hit.candidate.source_id))
        return MetadataRankResult(slot_id=slot_result.slot_id, ranked=tuple(scored))
