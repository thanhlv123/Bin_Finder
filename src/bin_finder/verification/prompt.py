from __future__ import annotations

from bin_finder.models import SceneRecord
from bin_finder.retrieval.models import RetrievalUnit


def verification_context(scene: SceneRecord) -> dict[str, object]:
    return {
        "scene_id": scene.scene_id,
        "script": scene.english_text,
        "subject": list(scene.context.subject),
        "action": list(scene.context.action),
        "location": list(scene.context.location),
        "objects": list(scene.context.objects),
        "mood": list(scene.context.mood),
        "avoid": list(scene.context.avoid),
    }


def build_verification_prompt(scene: SceneRecord, unit: RetrievalUnit) -> str:
    context = verification_context(scene)
    return (
        "Evaluate whether this footage segment matches the requested scene. "
        "Score subject_match, action_match, location_match, object_match, "
        "time_match, visual_quality, and context_conflict from 0 to 1. "
        f"Scene: {context}. "
        f"Segment timing: {unit.start:.3f}-{unit.end:.3f}s. "
        f"Transcript/metadata evidence: {unit.searchable_text!r}."
    )
