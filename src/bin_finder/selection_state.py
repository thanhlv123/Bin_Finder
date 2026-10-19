from __future__ import annotations

from dataclasses import dataclass, field

from bin_finder.models import CandidateRecord, SceneRecord


def _fallback_scene_order(scene_id: str) -> int:
    """Best-effort numeric order for ids such as scene_001."""
    try:
        return int(scene_id.rsplit("_", 1)[-1])
    except (TypeError, ValueError):
        return 10**9


@dataclass
class SceneSelectionIndex:
    """Keep exactly one selected candidate per scene in script order.

    The GUI uses this small pure-Python state object so replacement semantics can
    be tested without a Qt runtime. Re-selecting a scene replaces the candidate
    in-place logically; presentation order always follows script order.
    """

    scene_order: dict[str, int] = field(default_factory=dict)
    _candidates: dict[str, CandidateRecord] = field(default_factory=dict)

    @classmethod
    def from_scenes(cls, scenes: list[SceneRecord]) -> "SceneSelectionIndex":
        return cls({scene.scene_id: scene.order for scene in scenes})

    def update_scenes(self, scenes: list[SceneRecord]) -> None:
        self.scene_order = {scene.scene_id: scene.order for scene in scenes}
        valid = set(self.scene_order)
        self._candidates = {
            scene_id: candidate
            for scene_id, candidate in self._candidates.items()
            if scene_id in valid
        }

    def clear(self) -> None:
        self._candidates.clear()

    def add_or_replace(self, candidate: CandidateRecord) -> None:
        self._candidates[candidate.scene_id] = candidate

    def ordered_candidates(self) -> list[CandidateRecord]:
        return sorted(
            self._candidates.values(),
            key=lambda candidate: (
                self.scene_order.get(candidate.scene_id, _fallback_scene_order(candidate.scene_id)),
                candidate.scene_id,
            ),
        )

    def ordered_scene_ids(self) -> list[str]:
        return [candidate.scene_id for candidate in self.ordered_candidates()]

    def __len__(self) -> int:
        return len(self._candidates)
