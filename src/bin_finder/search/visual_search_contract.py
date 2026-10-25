"""BF-S01: Z5-inspired, independently designed semantic footage-search contract.

Pure data boundary between script understanding and search. This module does NOT
call an LLM, the network, providers, local files, CapCut or the production GUI.
This is a research-only model, not a reproduction of Z5 proprietary code.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from bin_finder.models import SceneRecord


FORMAT = "bin_finder_semantic_search_plan_v1"
_ID_RE = re.compile(r"[A-Za-z][A-Za-z0-9_:-]{0,79}\Z")
_ACTIONS = frozenset({"search", "hold", "transition", "graphic", "no_match"})
_ROLES = frozenset({"establish", "develop", "evidence", "context", "contrast",
                    "bridge", "conclude"})
_EVIDENCE = frozenset({"direct", "contextual", "symbolic", "not_applicable"})
_ENTITY_POLICY = frozenset({"strict", "contextual", "unspecified"})
_QUERY_AXES = ("subject", "moment", "action")
_MAX_SCENES = 1000
_MAX_BEATS = 250
_MAX_SLOTS = 1000


class SearchPlanError(ValueError):
    """Stable validation reason; never include script or model output in errors."""


def _string(value: object, code: str, limit: int = 350) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise SearchPlanError(code)
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise SearchPlanError(code)
    return " ".join(value.split())


def _id(value: object, code: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise SearchPlanError(code)
    return value


def _text_list(value: object, code: str, maximum: int = 8) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum:
        raise SearchPlanError(code)
    result = tuple(_string(item, code, 120) for item in value)
    if len({item.casefold() for item in result}) != len(result):
        raise SearchPlanError("duplicate-" + code)
    return result


def _ids(value: object, code: str, maximum: int = _MAX_SCENES) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise SearchPlanError(code)
    result = tuple(_id(item, code) for item in value)
    if len(set(result)) != len(result):
        raise SearchPlanError("duplicate-" + code)
    return result


def _rows(value: object, code: str, maximum: int) -> list[Mapping]:
    if (not isinstance(value, list) or not 1 <= len(value) <= maximum
            or any(not isinstance(v, Mapping) for v in value)):
        raise SearchPlanError(code)
    return value


def _enum(value: object, allowed: frozenset[str], code: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise SearchPlanError(code)
    return value


def _grounded(anchor: str, scenes: Sequence[SceneRecord]) -> bool:
    original = " ".join(" ".join(scene.english_text.split()) for scene in scenes)
    # The anchor is an exact source excerpt, not a generated semantic summary.
    return " ".join(anchor.split()).casefold() in original.casefold()


def _check_scenes(scenes: Sequence[SceneRecord]) -> tuple[str, ...]:
    if (not isinstance(scenes, (tuple, list))
            or not 1 <= len(scenes) <= _MAX_SCENES
            or any(not isinstance(s, SceneRecord) for s in scenes)):
        raise SearchPlanError("invalid-scenes")
    ids: list[str] = []
    for i, scene in enumerate(scenes, 1):
        _id(scene.scene_id, "invalid-scene-id")
        if type(scene.order) is not int or scene.order != i:
            raise SearchPlanError("unordered-scenes")
        if (not isinstance(scene.english_text, str)
                or not scene.english_text.strip()
                or len(scene.english_text) > 4000
                or not isinstance(scene.vietnamese_text, str)
                or len(scene.vietnamese_text) > 4000):
            raise SearchPlanError("invalid-scene-text")
        ids.append(scene.scene_id)
    if len(set(ids)) != len(ids):
        raise SearchPlanError("duplicate-scene-ids")
    return tuple(ids)


def script_digest(scenes: Sequence[SceneRecord]) -> str:
    """Stable input identity; changes in source narration invalidate stale plans."""
    _check_scenes(scenes)
    payload = [
        [scene.scene_id, scene.order, scene.english_text, scene.vietnamese_text]
        for scene in scenes
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class Beat:
    beat_id: str
    scene_ids: tuple[str, ...]
    meaning: str
    anchor_text: str
    section_context: str
    metaphor_note: str


@dataclass(frozen=True)
class VisualQuery:
    axis: str
    text: str


@dataclass(frozen=True)
class VisualSlot:
    slot_id: str
    beat_id: str
    scene_ids: tuple[str, ...]
    role: str
    action: str
    evidence_type: str
    entity_policy: str
    source_text: str
    visual_brief: str
    must_show: tuple[str, ...]
    must_not_show: tuple[str, ...]
    required_entities: tuple[str, ...]
    queries: tuple[VisualQuery, ...]
    reuse_from_slot_id: str | None
    uncertainty: str


@dataclass(frozen=True)
class SlotSearchRequest:
    """Provider-neutral input for a FUTURE adapter; no requests are executed."""
    slot_id: str
    beat_id: str
    scene_ids: tuple[str, ...]
    visual_brief: str
    evidence_type: str
    entity_policy: str
    required_entities: tuple[str, ...]
    must_show: tuple[str, ...]
    must_not_show: tuple[str, ...]
    queries: tuple[VisualQuery, ...]


@dataclass(frozen=True)
class SemanticSearchPlan:
    plan_id: str
    source_digest: str
    beats: tuple[Beat, ...]
    slots: tuple[VisualSlot, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "format": FORMAT,
            "plan_id": self.plan_id,
            "source_digest": self.source_digest,
            "beats": [
                {**asdict(beat), "scene_ids": list(beat.scene_ids)}
                for beat in self.beats
            ],
            "slots": [
                {
                    **asdict(slot),
                    "scene_ids": list(slot.scene_ids),
                    "must_show": list(slot.must_show),
                    "must_not_show": list(slot.must_not_show),
                    "required_entities": list(slot.required_entities),
                    "queries": [asdict(q) for q in slot.queries],
                }
                for slot in self.slots
            ],
        }

    def search_requests(self) -> tuple[SlotSearchRequest, ...]:
        return tuple(
            SlotSearchRequest(
                slot_id=s.slot_id,
                beat_id=s.beat_id,
                scene_ids=s.scene_ids,
                visual_brief=s.visual_brief,
                evidence_type=s.evidence_type,
                entity_policy=s.entity_policy,
                required_entities=s.required_entities,
                must_show=s.must_show,
                must_not_show=s.must_not_show,
                queries=s.queries,
            )
            for s in self.slots if s.action == "search"
        )

    def unresolved_slot_ids(self) -> tuple[str, ...]:
        return tuple(s.slot_id for s in self.slots
                     if s.action in {"transition", "graphic", "no_match"})


def parse_semantic_search_plan(
    payload: Mapping[str, object], scenes: Sequence[SceneRecord],
) -> SemanticSearchPlan:
    """Fail-closed validator for proposed beats, slots, and search query axes.

    Content correctness, evidence of historical facts, provider availability,
    and verified match quality remain outside this structural contract.
    """
    ids = _check_scenes(scenes)
    if not isinstance(payload, Mapping) or payload.get("format") != FORMAT:
        raise SearchPlanError("invalid-format")
    plan_id = _id(payload.get("plan_id"), "invalid-plan-id")
    digest = payload.get("source_digest")
    if not isinstance(digest, str) or digest != script_digest(scenes):
        raise SearchPlanError("stale-script")
    positions = {sid: i for i, sid in enumerate(ids)}

    beats: list[Beat] = []
    beat_lookup: dict[str, Beat] = {}
    flattened: list[str] = []
    for raw in _rows(payload.get("beats"), "invalid-beats", _MAX_BEATS):
        bid = _id(raw.get("beat_id"), "invalid-beat-id")
        if bid in beat_lookup:
            raise SearchPlanError("duplicate-beat-id")
        spans = _ids(raw.get("scene_ids"), "invalid-beat-scenes")
        if any(item not in positions for item in spans):
            raise SearchPlanError("unknown-beat-scene")
        bscenes = [scenes[positions[item]] for item in spans]
        anchor = _string(raw.get("anchor_text"), "invalid-beat-anchor", 300)
        if not _grounded(anchor, bscenes):
            raise SearchPlanError("ungrounded-beat-anchor")
        beat = Beat(
            beat_id=bid, scene_ids=spans,
            meaning=_string(raw.get("meaning"), "invalid-beat-meaning", 400),
            anchor_text=anchor,
            section_context=_string(raw.get("section_context"),
                                    "invalid-section-context", 500),
            metaphor_note=raw.get("metaphor_note", ""),
        )
        if not isinstance(beat.metaphor_note, str) or len(beat.metaphor_note) > 300:
            raise SearchPlanError("invalid-metaphor-note")
        beats.append(beat)
        beat_lookup[bid] = beat
        flattened.extend(spans)
    if tuple(flattened) != ids:
        raise SearchPlanError("beat-partition")

    slots: list[VisualSlot] = []
    used_ids: set[str] = set()
    coverage = {sid: 0 for sid in ids}
    last_start = -1
    last_visual_slot: str | None = None
    for raw in _rows(payload.get("slots"), "invalid-slots", _MAX_SLOTS):
        slot_id = _id(raw.get("slot_id"), "invalid-slot-id")
        if slot_id in used_ids:
            raise SearchPlanError("duplicate-slot-id")
        used_ids.add(slot_id)
        bid = _id(raw.get("beat_id"), "invalid-slot-beat")
        beat = beat_lookup.get(bid)
        if beat is None:
            raise SearchPlanError("unknown-slot-beat")
        spans = _ids(raw.get("scene_ids"), "invalid-slot-scenes")
        if any(sid not in positions for sid in spans):
            raise SearchPlanError("unknown-slot-scene")
        start = positions[spans[0]]
        if (start < last_start or ids[start:start + len(spans)] != spans
                or any(sid not in beat.scene_ids for sid in spans)):
            raise SearchPlanError("invalid-slot-order-or-span")
        last_start = start
        for sid in spans:
            coverage[sid] += 1
        source_text = _string(raw.get("source_text"), "invalid-slot-source", 300)
        if not _grounded(source_text, [scenes[positions[x]] for x in spans]):
            raise SearchPlanError("ungrounded-slot-source")
        action = _enum(raw.get("action"), _ACTIONS, "invalid-slot-action")
        evidence = _enum(raw.get("evidence_type"), _EVIDENCE,
                         "invalid-slot-evidence")
        role = _enum(raw.get("role"), _ROLES, "invalid-slot-role")
        entity_policy = _enum(raw.get("entity_policy"), _ENTITY_POLICY,
                              "invalid-entity-policy")
        must_show = _text_list(raw.get("must_show"), "invalid-must-show")
        must_not_show = _text_list(raw.get("must_not_show"), "invalid-must-not-show")
        entities = _text_list(raw.get("required_entities"), "invalid-required-entities")
        if {x.casefold() for x in must_show} & {x.casefold() for x in must_not_show}:
            raise SearchPlanError("contradictory-visual-constraints")
        raw_queries = raw.get("queries")
        if not isinstance(raw_queries, list) or len(raw_queries) > 3:
            raise SearchPlanError("invalid-queries")
        queries: list[VisualQuery] = []
        for query in raw_queries:
            if not isinstance(query, Mapping):
                raise SearchPlanError("invalid-query")
            axis = query.get("axis")
            if axis not in _QUERY_AXES:
                raise SearchPlanError("invalid-query-axis")
            queries.append(VisualQuery(
                axis=axis, text=_string(query.get("text"), "invalid-query-text", 160)
            ))
        hold_from = raw.get("reuse_from_slot_id")
        uncertainty = raw.get("uncertainty", "")
        if (not isinstance(uncertainty, str) or len(uncertainty) > 400
                or any(ord(c) < 32 and c not in "\t\n" for c in uncertainty)):
            raise SearchPlanError("invalid-uncertainty")
        if action == "search":
            if (len(queries) != 3
                    or tuple(q.axis for q in queries) != _QUERY_AXES
                    or len({q.text.casefold() for q in queries}) != 3
                    or not must_show or hold_from is not None
                    or evidence == "not_applicable"):
                raise SearchPlanError("invalid-search-slot")
        else:
            if (queries or must_show or must_not_show or entities
                    or evidence != "not_applicable"
                    or entity_policy != "unspecified"):
                raise SearchPlanError("invalid-nonsearch-slot")
            if action == "hold":
                if last_visual_slot is None or hold_from != last_visual_slot:
                    raise SearchPlanError("invalid-hold-reference")
            elif hold_from is not None:
                raise SearchPlanError("invalid-reuse-reference")
            if action == "no_match" and not uncertainty.strip():
                raise SearchPlanError("no-match-requires-explanation")
        slot = VisualSlot(
            slot_id=slot_id, beat_id=bid, scene_ids=spans,
            role=role, action=action, evidence_type=evidence,
            entity_policy=entity_policy, source_text=source_text,
            visual_brief=_string(raw.get("visual_brief"), "invalid-visual-brief", 400),
            must_show=must_show, must_not_show=must_not_show,
            required_entities=entities, queries=tuple(queries),
            reuse_from_slot_id=hold_from, uncertainty=uncertainty,
        )
        slots.append(slot)
        if action in {"search", "graphic"}:
            last_visual_slot = slot_id
        elif action == "hold":
            # A hold is a continuation of its referenced visual, not a new asset.
            pass
    if any(count == 0 for count in coverage.values()):
        raise SearchPlanError("uncovered-scenes")
    return SemanticSearchPlan(
        plan_id=plan_id, source_digest=digest,
        beats=tuple(beats), slots=tuple(slots),
    )
