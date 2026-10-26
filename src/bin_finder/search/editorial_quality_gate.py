"""BF-S04A.2 research: transparent human-defined editorial coverage checks.

An offline, read-only *quality advisory* for a structurally validated BF-S04A
shot plan. Independent fact checking, licensing, true semantic understanding
and suitability for publication are NOT performed here. Coverage vocabularies
must be written and reviewed by an editor BEFORE scoring the proposal.

No hidden model, network, provider, frame reading or timeline edits.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Sequence

from bin_finder.search.editorial_shot_plan import EditorialShotPlan


_ID = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_GENERIC_MUST_SHOW = frozenset({
    "visible documentary subject", "relevant scene",
    "documentary subject", "appropriate visual", "visual subject",
})
_REVIEW_TONES = frozenset({"somber", "suspense", "urgent"})


class EditorialQualityError(ValueError):
    """Sanitized fixed code; untrusted model text never enters the error."""


def _normalized_tokens(value: str) -> str:
    # Compare only explicitly preapproved observable phrases. The input is
    # untrusted narrative text, never executable or a remote search request.
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))


def _phrase_present(haystack: str, phrase: str) -> bool:
    words = _normalized_tokens(phrase)
    if not words:
        return False
    return (" " + words + " ") in (" " + haystack + " ")


@dataclass(frozen=True)
class CoverageRequirement:
    code: str
    description: str
    observable_phrases: tuple[str, ...]

    def __post_init__(self):
        if not _ID.fullmatch(self.code):
            raise EditorialQualityError("invalid-coverage-code")
        if (not self.description or len(self.description) > 160
                or not 1 <= len(self.observable_phrases) <= 16):
            raise EditorialQualityError("invalid-coverage-requirement")
        if any(
            not isinstance(p, str) or not p.strip() or len(p) > 120
            or not _normalized_tokens(p)
            for p in self.observable_phrases
        ):
            raise EditorialQualityError("invalid-coverage-phrase")


@dataclass(frozen=True)
class EditorialQualitySpecification:
    """User/editor-maintained target for a specific trusted BF-S01 slot."""
    slot_id: str
    requirements: tuple[CoverageRequirement, ...]
    needs_tone_change: bool = False

    def __post_init__(self):
        if (not isinstance(self.slot_id, str) or
                not re.fullmatch(r"[A-Za-z][A-Za-z0-9_:-]{0,79}", self.slot_id)):
            raise EditorialQualityError("invalid-quality-slot")
        if (not 1 <= len(self.requirements) <= 12
                or len({x.code for x in self.requirements}) != len(self.requirements)):
            raise EditorialQualityError("invalid-quality-requirements")
        if type(self.needs_tone_change) is not bool:
            raise EditorialQualityError("invalid-quality-tone-flag")


@dataclass(frozen=True)
class EditorialQualityReport:
    slot_id: str
    shot_count: int
    covered: tuple[str, ...]
    missing: tuple[str, ...]
    flags: tuple[str, ...]
    status: str = "quality-review-required"
    evidence_level: str = "heuristic-textual-coverage-not-visual-proof"

    def as_mapping(self) -> dict[str, object]:
        return {
            "slot_id": self.slot_id,
            "shot_count": self.shot_count,
            "covered": list(self.covered),
            "missing": list(self.missing),
            "flags": list(self.flags),
            "status": self.status,
            "evidence_level": self.evidence_level,
            "human_editorial_review_required": True,
            "footage_verified": False,
            "rights_approved": False,
            "timeline_approved": False,
        }


def review_editorial_quality(
    plan: EditorialShotPlan,
    spec: EditorialQualitySpecification,
) -> EditorialQualityReport:
    """Compare an editor's explicit requirements against requested visuals.

    CRUCIAL: do not score script anchors or must_not_show. They contain the
    original narration/exclusions, NOT what the footage will actually show.
    A keyword match in an AI proposal is not proof of a matching candidate.
    """
    if not isinstance(plan, EditorialShotPlan) or not isinstance(
        spec, EditorialQualitySpecification
    ):
        raise EditorialQualityError("invalid-quality-input")
    shots = tuple(s for s in plan.shots if s.slot_id == spec.slot_id)
    if not shots:
        raise EditorialQualityError("quality-slot-not-planned")

    texts = [
        _normalized_tokens(" ".join(
            [shot.visual_brief, *shot.must_show,
             *(query.text for query in shot.search_queries)]
        ))
        for shot in shots
    ]
    covered, missing = [], []
    for req in spec.requirements:
        if any(
            _phrase_present(text, phrase)
            for phrase in req.observable_phrases for text in texts
        ):
            covered.append(req.code)
        else:
            missing.append(req.code)

    flags: list[str] = []
    if missing:
        flags.append("editorial-coverage-incomplete")
    for shot in shots:
        if not shot.must_show or all(
            x.casefold().strip() in _GENERIC_MUST_SHOW
            for x in shot.must_show
        ):
            flags.append("generic-visible-criteria")
            break
    if spec.needs_tone_change and not any(
        shot.visual_tone in _REVIEW_TONES for shot in shots
    ):
        flags.append("missing-somber-or-suspense-transition")

    if len(shots) == 1 and len(spec.requirements) >= 3 and missing:
        flags.append("single-shot-editorial-compression-review")

    return EditorialQualityReport(
        slot_id=spec.slot_id, shot_count=len(shots),
        covered=tuple(covered), missing=tuple(missing),
        flags=tuple(dict.fromkeys(flags)),
    )


def savoie_editorial_reference() -> EditorialQualitySpecification:
    """Human-authored diagnostic target for user-provided Gaspard sample.

    This fixture deliberately does NOT require footage of an actual accident,
    injury, hospital scene, or unconscious person. The final event transition
    may be a graphic or a clearly labelled symbolic illustration instead.
    """
    return EditorialQualitySpecification(
        slot_id="slot2",
        requirements=(
            CoverageRequirement(
                "ski_location",
                "A clear outdoor Alpine skiing setting",
                ("alpine ski", "ski resort", "ski area", "station de ski"),
            ),
            CoverageRequirement(
                "savoie_context",
                "Distinguishable Savoie/La Rosiere geographic context",
                ("savoie", "la rosière", "la rosiere"),
            ),
            CoverageRequirement(
                "gentle_blue_piste",
                "A clearly marked easy blue piste",
                ("blue piste", "blue ski piste", "piste bleue",
                 "blue slope", "blue run", "blue trail"),
            ),
            CoverageRequirement(
                "skier_descending",
                "Visible skier moving down a gentle slope",
                ("skier descending", "skier gliding", "pov skier",
                 "skier skiing", "person skiing", "skiing down",
                 "skier moving down"),
            ),
            CoverageRequirement(
                "safe_afterfall_transition",
                "A non-fabricated editorial transition to the aftermath",
                ("unconscious", "after the fall", "incident aftermath",
                 "sudden silence", "cut to black", "fade to black",
                 "abrupt silence", "black screen title", "texte à l'écran"),
            ),
        ),
        needs_tone_change=True,
    )
