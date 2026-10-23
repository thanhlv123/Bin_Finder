"""ZB-02 research-only narrative-to-visual-plan contract.

Visual shots are not required to match narration scenes one-to-one:
one shot can span multiple scenes, and multiple shots can serve one scene.
No AI, Qt, providers, network, downloads, timeline export, or source selection.
This untrusted-plan boundary does NOT assert that a proposed image is truthful.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from bin_finder.models import SceneRecord


class VisualPlanningError(ValueError):
    """Fixed, non-sensitive reason why a visual plan is not safe to accept."""


_FORMAT = "bin_finder_visual_plan_v1"
_ROLES = frozenset({
    "establish", "develop", "contrast", "explain", "bridge", "conclude",
})
_STRATEGIES = frozenset({"search", "hold", "transition", "graphic"})
_EVIDENCE = frozenset({"direct", "contextual", "symbolic", "not_applicable"})


def _string(value: object, label: str, max_length: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise VisualPlanningError("invalid-" + label)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise VisualPlanningError("invalid-" + label)
    result = " ".join(value.split())
    if not result:
        raise VisualPlanningError("invalid-" + label)
    return result


def _items(value: object, label: str, *, maximum: int,
           max_length: int) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise VisualPlanningError("invalid-" + label)
    items = tuple(_string(item, label, max_length) for item in value)
    if len(set(items)) != len(items):
        raise VisualPlanningError("duplicate-" + label)
    return items


@dataclass(frozen=True)
class NarrativeBlock:
    block_id: str
    scene_ids: tuple[str, ...]
    role: str
    summary: str
    visual_purpose: str


@dataclass(frozen=True)
class VisualShot:
    shot_id: str
    block_id: str
    scene_ids: tuple[str, ...]
    strategy: str
    evidence_type: str
    visual_goal: str
    queries: tuple[str, ...]
    hold_from_shot_id: str | None


@dataclass(frozen=True)
class ShotSearchRequest:
    """Future provider adapter input: purpose and queries are separate."""
    shot_id: str
    scene_ids: tuple[str, ...]
    visual_goal: str
    evidence_type: str
    queries: tuple[str, ...]


@dataclass(frozen=True)
class VisualStoryPlan:
    plan_id: str
    blocks: tuple[NarrativeBlock, ...]
    shots: tuple[VisualShot, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "format": _FORMAT,
            "plan_id": self.plan_id,
            "blocks": [
                {**asdict(block), "scene_ids": list(block.scene_ids)}
                for block in self.blocks
            ],
            "shots": [
                {**asdict(shot), "scene_ids": list(shot.scene_ids),
                 "queries": list(shot.queries)}
                for shot in self.shots
            ],
        }

    def search_requests(self) -> tuple[ShotSearchRequest, ...]:
        """No search is performed. Non-search strategies produce NO requests."""
        return tuple(
            ShotSearchRequest(
                shot_id=shot.shot_id,
                scene_ids=shot.scene_ids,
                visual_goal=shot.visual_goal,
                evidence_type=shot.evidence_type,
                queries=shot.queries,
            )
            for shot in self.shots if shot.strategy == "search"
        )


def _rows(data: Mapping[str, object], field: str, maximum: int) -> list:
    value = data.get(field)
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise VisualPlanningError("invalid-" + field)
    if any(not isinstance(item, Mapping) for item in value):
        raise VisualPlanningError("invalid-" + field)
    return value


def parse_visual_story_plan(
    data: Mapping[str, object], scenes: Sequence[SceneRecord],
) -> VisualStoryPlan:
    """Validate a planning suggestion without interpreting or fetching footage.

    Existing SceneRecord identity/order is authoritative and never modified.
    Blocks partition scenes in order. Shots may overlap scenes or cover multiple
    adjacent scenes, but every scene needs some visual action.
    """
    if not isinstance(data, Mapping) or data.get("format") != _FORMAT:
        raise VisualPlanningError("invalid-format")
    if (not isinstance(scenes, (list, tuple))
            or not 1 <= len(scenes) <= 1000
            or any(not isinstance(scene, SceneRecord) for scene in scenes)):
        raise VisualPlanningError("invalid-scenes")
    if any(
        not isinstance(scene.scene_id, str) or not scene.scene_id
        or type(scene.order) is not int or scene.order != idx
        for idx, scene in enumerate(scenes, 1)
    ):
        raise VisualPlanningError("unordered-scenes")
    scene_ids = tuple(scene.scene_id for scene in scenes)
    if len(set(scene_ids)) != len(scene_ids):
        raise VisualPlanningError("duplicate-scene-ids")
    indices = {sid: idx for idx, sid in enumerate(scene_ids)}

    plan_id = _string(data.get("plan_id"), "plan-id", 100)
    raw_blocks = _rows(data, "blocks", 250)
    raw_shots = _rows(data, "shots", 2000)
    blocks: list[NarrativeBlock] = []
    block_by_id: dict[str, NarrativeBlock] = {}
    flattened: list[str] = []
    for raw in raw_blocks:
        bid = _string(raw.get("block_id"), "block-id", 100)
        if bid in block_by_id:
            raise VisualPlanningError("duplicate-block-id")
        spans = _items(raw.get("scene_ids"), "block-scenes", maximum=1000,
                       max_length=100)
        role = _string(raw.get("role"), "block-role", 40)
        if role not in _ROLES:
            raise VisualPlanningError("invalid-block-role")
        block = NarrativeBlock(
            block_id=bid, scene_ids=spans, role=role,
            summary=_string(raw.get("summary"), "summary", 500),
            visual_purpose=_string(raw.get("visual_purpose"), "visual-purpose", 300),
        )
        blocks.append(block)
        block_by_id[bid] = block
        flattened.extend(spans)
    if tuple(flattened) != scene_ids:
        raise VisualPlanningError("block-scene-partition")

    shots: list[VisualShot] = []
    seen_shots: set[str] = set()
    covered: set[str] = set()
    last_start = -1
    last_visual_shot: str | None = None
    for raw in raw_shots:
        sid = _string(raw.get("shot_id"), "shot-id", 100)
        if sid in seen_shots:
            raise VisualPlanningError("duplicate-shot-id")
        seen_shots.add(sid)
        bid = _string(raw.get("block_id"), "shot-block-id", 100)
        block = block_by_id.get(bid)
        if block is None:
            raise VisualPlanningError("unknown-shot-block")
        spans = _items(raw.get("scene_ids"), "shot-scenes", maximum=1000,
                       max_length=100)
        # The shot covers a contiguous range within one narrative block.
        if any(item not in indices for item in spans):
            raise VisualPlanningError("unknown-shot-scene")
        start = indices[spans[0]]
        if (start < last_start
                or tuple(scene_ids[start:start + len(spans)]) != spans
                or any(item not in block.scene_ids for item in spans)):
            raise VisualPlanningError("invalid-shot-order-or-span")
        last_start = start
        covered.update(spans)
        strategy = _string(raw.get("strategy"), "strategy", 40)
        evidence = _string(raw.get("evidence_type"), "evidence", 40)
        if strategy not in _STRATEGIES or evidence not in _EVIDENCE:
            raise VisualPlanningError("invalid-strategy-or-evidence")
        raw_queries = raw.get("queries")
        if not isinstance(raw_queries, list) or len(raw_queries) > 3:
            raise VisualPlanningError("invalid-shot-queries")
        queries = tuple(_string(q, "shot-query", 160) for q in raw_queries)
        if len(set(q.casefold() for q in queries)) != len(queries):
            raise VisualPlanningError("duplicate-shot-query")
        inherited = raw.get("hold_from_shot_id")
        if strategy == "search":
            if not queries or inherited is not None or evidence == "not_applicable":
                raise VisualPlanningError("invalid-search-shot")
        elif strategy == "hold":
            if (queries or not isinstance(inherited, str)
                    or inherited != last_visual_shot
                    or evidence != "not_applicable"):
                raise VisualPlanningError("invalid-hold-shot")
        else:
            if queries or inherited is not None or evidence != "not_applicable":
                raise VisualPlanningError("invalid-nonsearch-shot")
        shot = VisualShot(
            shot_id=sid, block_id=bid, scene_ids=spans,
            strategy=strategy, evidence_type=evidence,
            visual_goal=_string(raw.get("visual_goal"), "visual-goal", 300),
            queries=queries, hold_from_shot_id=inherited,
        )
        shots.append(shot)
        if strategy in {"search", "hold", "graphic"}:
            last_visual_shot = sid
    if covered != set(scene_ids):
        raise VisualPlanningError("uncovered-narration-scenes")
    return VisualStoryPlan(plan_id, tuple(blocks), tuple(shots))
