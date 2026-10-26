"""BF-S04A: bounded editorial shot plan contract, built on BF-S01 VisualSlots.

No model/provider/network access or automatic fact, media, rights, or timeline
approval. AI may *propose* shot payloads; this module only validates them.
Original reportage vs illustrative stock is an explicit editorial decision.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Mapping, Sequence

from bin_finder.models import SceneRecord
from bin_finder.search.visual_search_contract import (
    SemanticSearchPlan, script_digest,
)

FORMAT = "bin_finder_editorial_shot_plan_v1"
_MAX_SHOTS = 1000
_MAX_PER_SLOT = 8
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_:-]{0,79}\Z")
_KINDS = frozenset({
    "authentic_person", "authentic_event", "location_context",
    "illustrative_stock", "symbolic", "graphic",
})
_MEDIA = frozenset({"video", "image", "graphic"})
_QUERY_LANGUAGES = frozenset({"en", "fr", "vi", "es", "de"})
_FALLBACKS = frozenset({
    "no_match", "graphic_with_source", "contextual_illustration_labeled",
    "symbolic_labeled",
})
_TONES = frozenset({
    "neutral", "urgent", "somber", "suspense", "nostalgic", "warm",
})
_ROUTES = {
    "authentic_person": "licensed_archive_human_review",
    "authentic_event": "licensed_archive_human_review",
    "location_context": "contextual_stock_search",
    "illustrative_stock": "contextual_stock_search",
    "symbolic": "symbolic_stock_search",
    "graphic": "graphic_composition",
}


class EditorialShotPlanError(ValueError):
    """Stable code only; no untrusted script text or path in exception."""


def _fail(code: str):
    raise EditorialShotPlanError(code)


def _id(value, code: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail(code)
    return value


def _text(value, code: str, limit: int = 400) -> str:
    if (not isinstance(value, str) or not value.strip()
            or len(value) > limit
            or any(ord(x) < 32 or ord(x) == 127 for x in value)):
        _fail(code)
    return " ".join(value.split())


def _list(value, code: str, *, max_items=8, allow_empty=True) -> tuple[str, ...]:
    if (not isinstance(value, list) or len(value) > max_items
            or (not allow_empty and not value)):
        _fail(code)
    result = tuple(_text(x, code, 120) for x in value)
    if len(set(x.casefold() for x in result)) != len(result):
        _fail(code)
    return result


def _enum(value, allowed, code: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        _fail(code)
    return value


def _grounded(anchor: str, source: str) -> bool:
    return " ".join(anchor.casefold().split()) in " ".join(source.casefold().split())


@dataclass(frozen=True)
class ShotQuery:
    language: str
    text: str


@dataclass(frozen=True)
class EditorialShot:
    shot_id: str
    slot_id: str
    beat_id: str
    scene_ids: tuple[str, ...]
    source_anchor: str
    visual_brief: str
    asset_evidence_type: str
    media_type: str
    target_duration_seconds: float
    visual_tone: str
    must_show: tuple[str, ...]
    must_not_show: tuple[str, ...]
    search_queries: tuple[ShotQuery, ...]
    fallback_policy: str
    source_route: str
    evidence_notice: str
    factual_status: str = "unverified"
    rights_status: str = "pending"
    timeline_approved: bool = False

    def to_mapping(self) -> dict:
        return {
            "shot_id": self.shot_id,
            "slot_id": self.slot_id,
            "beat_id": self.beat_id,
            "scene_ids": list(self.scene_ids),
            "source_anchor": self.source_anchor,
            "visual_brief": self.visual_brief,
            "asset_evidence_type": self.asset_evidence_type,
            "media_type": self.media_type,
            "target_duration_seconds": self.target_duration_seconds,
            "visual_tone": self.visual_tone,
            "must_show": list(self.must_show),
            "must_not_show": list(self.must_not_show),
            "search_queries": [
                {"language": q.language, "text": q.text}
                for q in self.search_queries
            ],
            "fallback_policy": self.fallback_policy,
            "source_route": self.source_route,
            "evidence_notice": self.evidence_notice,
            "factual_status": self.factual_status,
            "rights_status": self.rights_status,
            "timeline_approved": self.timeline_approved,
        }


@dataclass(frozen=True)
class EditorialShotPlan:
    plan_id: str
    base_plan_id: str
    source_digest: str
    shots: tuple[EditorialShot, ...]
    status: str = "proposal-only-unverified"

    def to_mapping(self) -> dict:
        return {
            "format": FORMAT,
            "plan_id": self.plan_id,
            "base_plan_id": self.base_plan_id,
            "source_digest": self.source_digest,
            "status": self.status,
            "shots": [s.to_mapping() for s in self.shots],
        }

    def route_counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for shot in self.shots:
            result[shot.source_route] = result.get(shot.source_route, 0) + 1
        return result

    def stock_candidates_to_research(self) -> tuple[EditorialShot, ...]:
        """Only requests; this does not call BF-S02 providers or return URLs."""
        return tuple(
            shot for shot in self.shots
            if shot.source_route.endswith("stock_search")
        )


def _notice(kind: str) -> str:
    if kind == "authentic_event":
        return "historical-event-source-and-rights-not-verified"
    if kind == "authentic_person":
        return "person-identity-and-rights-not-verified"
    if kind == "graphic":
        return "text-facts-and-rights-need-editorial-review"
    return "illustration-not-evidence-of-historical-event"


def parse_editorial_shot_plan(
    payload: Mapping[str, object],
    base: SemanticSearchPlan,
    scenes: Sequence[SceneRecord],
) -> EditorialShotPlan:
    """Fail-closed adapter for human/AI-proposed 1-5 second shots.

    The original BF-S01 plan remains the canonical scene/beat/slot identity.
    Input order must follow slot order; multiple shots may share a slot.
    """
    if not isinstance(base, SemanticSearchPlan):
        _fail("invalid-base-plan")
    try:
        digest = script_digest(scenes)
    except (ValueError, TypeError):
        _fail("invalid-scenes")
    if digest != base.source_digest:
        _fail("stale-source-scenes")
    if (not isinstance(payload, Mapping) or payload.get("format") != FORMAT):
        _fail("invalid-shot-format")
    plan_id = _id(payload.get("plan_id"), "invalid-shot-plan-id")
    if payload.get("base_plan_id") != base.plan_id:
        _fail("mismatched-base-plan")
    if payload.get("source_digest") != digest:
        _fail("stale-editorial-plan")
    if payload.get("status", "proposal-only-unverified") != "proposal-only-unverified":
        _fail("invalid-editorial-status")
    rows = payload.get("shots")
    if (not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_SHOTS
            or any(not isinstance(row, Mapping) for row in rows)):
        _fail("invalid-shot-list")

    slot_positions = {s.slot_id: i for i, s in enumerate(base.slots)}
    slot_map = {s.slot_id: s for s in base.slots}
    scene_map = {s.scene_id: s for s in scenes}
    seen: set[str] = set()
    counts: dict[str, int] = {}
    last_position = -1
    shots: list[EditorialShot] = []

    for row in rows:
        shot_id = _id(row.get("shot_id"), "invalid-shot-id")
        if shot_id in seen:
            _fail("duplicate-shot-id")
        seen.add(shot_id)
        sid = _id(row.get("slot_id"), "invalid-shot-slot")
        slot = slot_map.get(sid)
        if slot is None:
            _fail("unknown-shot-slot")
        pos = slot_positions[sid]
        if pos < last_position:
            _fail("unordered-shots")
        last_position = pos
        counts[sid] = counts.get(sid, 0) + 1
        if counts[sid] > _MAX_PER_SLOT:
            _fail("too-many-shots-per-slot")
        if slot.action not in {"search", "graphic"}:
            _fail("cannot-illustrate-nonvisual-slot")
        if "beat_id" in row and row["beat_id"] != slot.beat_id:
            _fail("mismatched-shot-beat")
        if "scene_ids" in row and row["scene_ids"] != list(slot.scene_ids):
            _fail("mismatched-shot-scenes")
        anchor = _text(row.get("source_anchor"), "invalid-shot-anchor", 300)
        original = " ".join(scene_map[k].english_text for k in slot.scene_ids)
        if not _grounded(anchor, original):
            _fail("ungrounded-shot-anchor")
        brief = _text(row.get("visual_brief"), "invalid-shot-brief", 400)
        kind = _enum(row.get("asset_evidence_type"), _KINDS, "invalid-asset-kind")
        media = _enum(row.get("media_type"), _MEDIA, "invalid-shot-media")
        if (slot.action == "graphic" and kind != "graphic"
                or (kind == "graphic") != (media == "graphic")):
            _fail("invalid-shot-media-route")
        duration = row.get("target_duration_seconds")
        if (type(duration) not in (float, int)
                or not math.isfinite(duration) or not 1 <= duration <= 5):
            _fail("invalid-shot-duration")
        tone = _enum(row.get("visual_tone"), _TONES, "invalid-shot-tone")
        must_show = _list(row.get("must_show"), "invalid-shot-must-show")
        must_not_show = _list(row.get("must_not_show"), "invalid-shot-must-not-show")
        if set(x.casefold() for x in must_show) & set(x.casefold() for x in must_not_show):
            _fail("contradictory-shot-constraints")
        if kind != "graphic" and not must_show:
            _fail("missing-shot-visible-criteria")
        if kind in {"illustrative_stock", "location_context", "symbolic"}:
            # Inherited BF-S01 exclusions cannot silently disappear.
            if not set(x.casefold() for x in slot.must_not_show).issubset(
                x.casefold() for x in must_not_show
            ):
                _fail("missing-parent-exclusions")
        fallback = _enum(row.get("fallback_policy"), _FALLBACKS,
                         "invalid-shot-fallback")
        if (kind in {"authentic_person", "authentic_event", "graphic"}
                and fallback not in {"no_match", "graphic_with_source"}):
            _fail("unsafe-authentic-fallback")
        if kind != "graphic" and slot.action == "graphic":
            _fail("invalid-shot-media-route")

        queries = row.get("search_queries")
        if not isinstance(queries, list) or len(queries) > 6:
            _fail("invalid-shot-queries")
        if (kind == "graphic" and queries
                or kind != "graphic" and not queries):
            _fail("invalid-shot-queries")
        parsed: list[ShotQuery] = []
        for query in queries:
            if not isinstance(query, Mapping):
                _fail("invalid-shot-query")
            parsed.append(ShotQuery(
                language=_enum(query.get("language"), _QUERY_LANGUAGES,
                               "invalid-shot-language"),
                text=_text(query.get("text"), "invalid-shot-query-text", 160),
            ))
        if len({(q.language, q.text.casefold()) for q in parsed}) != len(parsed):
            _fail("duplicate-shot-query")
        route = _ROUTES[kind]
        notice = _notice(kind)
        if "source_route" in row and row["source_route"] != route:
            _fail("forged-source-route")
        if "evidence_notice" in row and row["evidence_notice"] != notice:
            _fail("forged-evidence-notice")
        if row.get("factual_status", "unverified") != "unverified":
            _fail("forged-fact-verification")
        if row.get("rights_status", "pending") != "pending":
            _fail("forged-rights-approval")
        if row.get("timeline_approved", False) is not False:
            _fail("forged-timeline-approval")
        shots.append(EditorialShot(
            shot_id=shot_id, slot_id=sid, beat_id=slot.beat_id,
            scene_ids=slot.scene_ids, source_anchor=anchor,
            visual_brief=brief, asset_evidence_type=kind,
            media_type=media, target_duration_seconds=float(duration),
            visual_tone=tone, must_show=must_show, must_not_show=must_not_show,
            search_queries=tuple(parsed), fallback_policy=fallback,
            source_route=route, evidence_notice=notice,
        ))

    if any(s.action in {"search", "graphic"} and counts.get(s.slot_id, 0) == 0
           for s in base.slots):
        _fail("uncovered-visual-slot")
    return EditorialShotPlan(
        plan_id=plan_id, base_plan_id=base.plan_id,
        source_digest=digest, shots=tuple(shots),
    )
