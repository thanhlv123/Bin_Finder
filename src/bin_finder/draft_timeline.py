"""ZB-03A isolated storyboard review state. This is NOT a renderable timeline.

Scene timing here is estimated NARRATION range only; overlapping shots are not
scheduled within those ranges. Candidate references are user-review placeholders,
NOT F014 approvals, verified footage, licensed rights or export-eligible clips.
No Qt, disk IO, provider, download, Ollama, or production state mutation.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping, Sequence

from bin_finder.models import SceneRecord
from bin_finder.visual_planning import VisualStoryPlan, parse_visual_story_plan


class DraftTimelineError(ValueError):
    """Stable non-sensitive error code."""


_ALLOWED_ORIGINS = frozenset({"synthetic", "local"})
_ID = re.compile(r"[a-zA-Z0-9_:-]{1,100}\Z")
_MAX_CANDIDATES = 20


def _text(value: object, code: str, limit: int = 300) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise DraftTimelineError(code)
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise DraftTimelineError(code)
    return value.strip()


@dataclass(frozen=True)
class DraftCandidate:
    candidate_id: str
    title: str
    origin: str = "synthetic"
    local_file: str = ""

    def __post_init__(self):
        if not isinstance(self.candidate_id, str) or not _ID.fullmatch(self.candidate_id):
            raise DraftTimelineError("invalid-candidate-id")
        _text(self.title, "invalid-candidate-title", 180)
        if self.origin not in _ALLOWED_ORIGINS:
            raise DraftTimelineError("invalid-candidate-origin")
        if not isinstance(self.local_file, str) or len(self.local_file) > 4096:
            raise DraftTimelineError("invalid-local-path")
        if (self.origin == "synthetic" and self.local_file
                or self.origin == "local" and not self.local_file):
            raise DraftTimelineError("invalid-candidate-source")


@dataclass(frozen=True)
class DraftTimelineItem:
    shot_id: str
    block_id: str
    scene_ids: tuple[str, ...]
    strategy: str
    evidence_type: str
    visual_goal: str
    narration_start_estimate: float
    narration_end_estimate: float
    candidates: tuple[DraftCandidate, ...] = ()
    selected_candidate_id: str | None = None
    reviewed: bool = False
    locked: bool = False
    note: str = ""

    @property
    def review_status(self) -> str:
        if self.locked:
            return "locked"
        if self.strategy != "search":
            return "needs_editorial_resolution"
        if self.reviewed:
            return "reviewed"
        if self.selected_candidate_id:
            return "proposed"
        return "missing"


@dataclass(frozen=True)
class DraftTimeline:
    """Immutable review overlay on an independently validated ZB-02 storyboard."""
    plan_id: str
    items: tuple[DraftTimelineItem, ...]
    scene_ids: tuple[str, ...]

    def item(self, shot_id: str) -> DraftTimelineItem:
        for item in self.items:
            if item.shot_id == shot_id:
                return item
        raise DraftTimelineError("unknown-shot")

    def _replace(self, new: DraftTimelineItem) -> DraftTimeline:
        return replace(self, items=tuple(
            new if item.shot_id == new.shot_id else item for item in self.items
        ))

    def choose(self, shot_id: str, candidate_id: str | None) -> DraftTimeline:
        item = self.item(shot_id)
        if item.locked:
            raise DraftTimelineError("shot-locked")
        if item.strategy != "search":
            raise DraftTimelineError("shot-does-not-search")
        if candidate_id is not None and candidate_id not in {
            candidate.candidate_id for candidate in item.candidates
        }:
            raise DraftTimelineError("unknown-candidate")
        return self._replace(replace(
            item, selected_candidate_id=candidate_id, reviewed=False
        ))

    def add_candidate(self, shot_id: str, candidate: DraftCandidate) -> DraftTimeline:
        item = self.item(shot_id)
        if item.locked:
            raise DraftTimelineError("shot-locked")
        if item.strategy != "search":
            raise DraftTimelineError("shot-does-not-search")
        if len(item.candidates) >= _MAX_CANDIDATES:
            raise DraftTimelineError("too-many-candidates")
        if any(c.candidate_id == candidate.candidate_id for c in item.candidates):
            raise DraftTimelineError("duplicate-candidate")
        if not isinstance(candidate, DraftCandidate):
            raise DraftTimelineError("invalid-candidate")
        return self._replace(replace(
            item, candidates=item.candidates + (candidate,)
        ))

    def mark_reviewed(self, shot_id: str) -> DraftTimeline:
        """Confirms editorial placement only; NEVER F014 final media approval."""
        item = self.item(shot_id)
        if item.locked:
            raise DraftTimelineError("shot-locked")
        if item.strategy != "search" or not item.selected_candidate_id:
            raise DraftTimelineError("candidate-not-selected")
        return self._replace(replace(item, reviewed=True))

    def set_lock(self, shot_id: str, locked: bool) -> DraftTimeline:
        if type(locked) is not bool:
            raise DraftTimelineError("invalid-lock-value")
        item = self.item(shot_id)
        if locked and (item.strategy != "search" or not item.reviewed):
            raise DraftTimelineError("review-required-before-lock")
        return self._replace(replace(item, locked=locked))

    def set_note(self, shot_id: str, note: str) -> DraftTimeline:
        item = self.item(shot_id)
        if item.locked:
            raise DraftTimelineError("shot-locked")
        if not isinstance(note, str) or len(note) > 500 or any(
            ord(c) < 32 and c not in "\t\n" for c in note
        ):
            raise DraftTimelineError("invalid-review-note")
        return self._replace(replace(item, note=note))

    def counts(self) -> dict[str, int]:
        return {
            status: sum(item.review_status == status for item in self.items)
            for status in ("missing", "proposed", "reviewed", "locked",
                           "needs_editorial_resolution")
        }


def _estimates(scenes: Sequence[SceneRecord]) -> tuple[dict[str, float], dict[str, float]]:
    start: dict[str, float] = {}
    end: dict[str, float] = {}
    current = 0.0
    for scene in scenes:
        if type(scene.target_duration) not in (int, float) or not (
            math.isfinite(scene.target_duration) and 0 < scene.target_duration <= 3600
        ):
            raise DraftTimelineError("invalid-narration-duration")
        start[scene.scene_id] = round(current, 2)
        current += scene.target_duration
        end[scene.scene_id] = round(current, 2)
    return start, end


def build_draft_timeline(
    plan: VisualStoryPlan, scenes: Sequence[SceneRecord],
    candidates_by_shot: Mapping[str, Sequence[DraftCandidate]] | None = None,
) -> DraftTimeline:
    """Create in-memory editor state; NEVER download, approve or produce media."""
    if not isinstance(plan, VisualStoryPlan):
        raise DraftTimelineError("invalid-plan")
    parsed = parse_visual_story_plan(plan.to_mapping(), scenes)
    if parsed != plan:
        raise DraftTimelineError("invalid-plan")
    first, last = _estimates(scenes)
    offered = candidates_by_shot or {}
    if not isinstance(offered, Mapping) or set(offered) - {
        shot.shot_id for shot in plan.shots
    }:
        raise DraftTimelineError("unknown-candidate-shot")
    items: list[DraftTimelineItem] = []
    for shot in plan.shots:
        candidates = offered.get(shot.shot_id, ())
        if not isinstance(candidates, (list, tuple)) or len(candidates) > _MAX_CANDIDATES:
            raise DraftTimelineError("invalid-candidate-list")
        if any(not isinstance(candidate, DraftCandidate) for candidate in candidates):
            raise DraftTimelineError("invalid-candidate")
        if len({c.candidate_id for c in candidates}) != len(candidates):
            raise DraftTimelineError("duplicate-candidate")
        if shot.strategy != "search" and candidates:
            raise DraftTimelineError("nonsearch-has-candidates")
        items.append(DraftTimelineItem(
            shot_id=shot.shot_id, block_id=shot.block_id,
            scene_ids=shot.scene_ids, strategy=shot.strategy,
            evidence_type=shot.evidence_type, visual_goal=shot.visual_goal,
            narration_start_estimate=first[shot.scene_ids[0]],
            narration_end_estimate=last[shot.scene_ids[-1]],
            candidates=tuple(candidates),
            selected_candidate_id=candidates[0].candidate_id if candidates else None,
        ))
    return DraftTimeline(
        plan_id=plan.plan_id, items=tuple(items),
        scene_ids=tuple(scene.scene_id for scene in scenes),
    )


def local_candidate_for_path(path: str) -> DraftCandidate:
    """Build an unverified local candidate reference from explicit user selection.

    File existence and type are checked, but media identity, quality, and usage
    rights are NOT verified. Does not open or decode the video itself.
    """
    if not isinstance(path, str) or len(path) > 4096:
        raise DraftTimelineError("invalid-local-path")
    source = Path(path).expanduser()
    if source.is_symlink() or not source.is_file():
        raise DraftTimelineError("local-file-not-regular")
    if source.suffix.lower() not in {".mp4", ".mkv", ".mov", ".webm"}:
        raise DraftTimelineError("unsupported-local-format")
    resolved = str(source.resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:24]
    return DraftCandidate(
        candidate_id="local_" + digest,
        title=source.name[:180],
        origin="local",
        local_file=resolved,
    )
