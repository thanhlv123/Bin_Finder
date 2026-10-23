"""ZB-02B read-only visual-plan audit (not semantic truth verification).

An accepted storyboard can be structurally valid and still have editorial
coverage or stock-search concerns. Flags ask for review; never reject, replace,
alter, search, download, or imply media/timing truth.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Sequence

from bin_finder.models import SceneRecord
from bin_finder.visual_planning import (
    VisualStoryPlan, VisualPlanningError, parse_visual_story_plan,
)

# Review only: a stock video of a chart is not a sourced chart. Some legitimately
# reusable footage may contain a chart, so this must NEVER auto-rewrite a shot.
_DATA_GRAPHIC = re.compile(
    r"\b(?:charts?|graphs?|infographics?|data visuali[sz]ations?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VisualAuditFlag:
    code: str
    shot_id: str
    scene_ids: tuple[str, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            "code": self.code,
            "shot_id": self.shot_id,
            "scene_ids": list(self.scene_ids),
        }


@dataclass(frozen=True)
class VisualPlanAudit:
    scene_count: int
    block_count: int
    shot_count: int
    search_count: int
    hold_count: int
    transition_count: int
    graphic_count: int
    multi_scene_shot_count: int
    scenes_with_multiple_shots: int
    flags: tuple[VisualAuditFlag, ...]

    def to_mapping(self) -> dict[str, object]:
        return {
            **{key: value for key, value in asdict(self).items() if key != "flags"},
            "flags": [flag.to_mapping() for flag in self.flags],
        }


def audit_visual_story_plan(
    plan: VisualStoryPlan, scenes: Sequence[SceneRecord],
) -> VisualPlanAudit:
    """Check planning coverage, not actual footage or narration alignment.

    Validate again so callers cannot hand in a forged/dangling dataclass.
    Transition-only coverage needs a later scheduler decision, not more
    automatic stock searches. Counts do not imply editorial quality.
    """
    if not isinstance(plan, VisualStoryPlan):
        raise VisualPlanningError("invalid-audit-plan")
    # Fail closed for invalid manual constructions. Do not modify the input.
    checked = parse_visual_story_plan(plan.to_mapping(), scenes)
    if checked != plan:
        raise VisualPlanningError("invalid-audit-plan")

    flags: list[VisualAuditFlag] = []
    by_scene: dict[str, list] = {scene.scene_id: [] for scene in scenes}
    searches = holds = transitions = graphics = 0
    multi_scene_shots = 0
    for shot in plan.shots:
        for sid in shot.scene_ids:
            by_scene[sid].append(shot)
        multi_scene_shots += len(shot.scene_ids) > 1
        if shot.strategy == "search":
            searches += 1
            material = shot.visual_goal + " " + " ".join(shot.queries)
            if _DATA_GRAPHIC.search(material):
                flags.append(VisualAuditFlag(
                    "graphic-like-content-routed-to-stock-search",
                    shot.shot_id, shot.scene_ids,
                ))
        elif shot.strategy == "hold":
            holds += 1
        elif shot.strategy == "transition":
            transitions += 1
        elif shot.strategy == "graphic":
            graphics += 1

    for scene in scenes:
        covering = by_scene[scene.scene_id]
        if covering and all(shot.strategy == "transition" for shot in covering):
            flags.append(VisualAuditFlag(
                "transition-only-visual-coverage-unresolved",
                covering[0].shot_id, (scene.scene_id,),
            ))
    return VisualPlanAudit(
        scene_count=len(scenes),
        block_count=len(plan.blocks),
        shot_count=len(plan.shots),
        search_count=searches,
        hold_count=holds,
        transition_count=transitions,
        graphic_count=graphics,
        multi_scene_shot_count=multi_scene_shots,
        scenes_with_multiple_shots=sum(len(items) > 1 for items in by_scene.values()),
        flags=tuple(flags),
    )
