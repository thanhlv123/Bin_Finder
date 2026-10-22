"""F016 fail-closed restoration of explicitly approved local media.

Never use the stored selection list directly as authoritative GUI or export state.
The codec checks structure; this module checks on-disk source identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.final_selection import build_final_project
from bin_finder.models import SceneRecord, SelectedClipRecord
from bin_finder.session_codec import scene_from_data, validate_snapshot
from bin_finder.session_workflow import restore_workflow_refs


@dataclass(frozen=True)
class RestoredSession:
    project_id: str
    scenes: tuple[SceneRecord, ...]
    final_selections: tuple[SelectedClipRecord, ...]
    unresolved: tuple[tuple[str, str], ...]
    ui_state: dict[str, str]
    workflow_refs: tuple[dict[str, str], ...] = ()


def _safe_regular_file(value):
    path = Path(value)
    if not path.is_absolute():
        return None
    # Reject symlinks and Windows junctions in the entire source path.
    for entry in (path, *path.parents):
        if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
            return None
    if not path.is_file() or path.stat().st_size <= 0:
        return None
    return path


def restore_session(payload) -> RestoredSession:
    """Return only revalidated final selections; stale scenes stay unresolved.

    Remote-origin selections cannot be reauthorized from F014's final record
    alone (the F012 acquisition manifest is not stored), so they fail closed.
    """
    snapshot = validate_snapshot(payload)
    scenes = tuple(scene_from_data(item) for item in snapshot["scenes"])
    selections = []
    unresolved = []
    for row in snapshot["final_selections"]:
        scene_id = row["scene_id"]
        if row["provider"] != "local":
            unresolved.append((scene_id, "remote-provenance-required"))
            continue
        try:
            path = _safe_regular_file(row["local_file"])
            if path is None:
                unresolved.append((scene_id, "local-media-unavailable"))
                continue
            if fingerprint_file(path).sha256 != row["source_metadata"]["media_sha256"]:
                unresolved.append((scene_id, "media-identity-changed"))
                continue
            clip = SelectedClipRecord(
                clip_id=row["clip_id"], scene_id=scene_id,
                scene_order=row["scene_order"], provider=row["provider"],
                source_id=row["source_id"], title=row["title"],
                local_file=str(path), start=row["start"], end=row["end"],
                duration=row["duration"], semantic_score=row["semantic_score"],
                vlm_score=row["vlm_score"], final_score=row["final_score"],
                rights_status=row["rights_status"], creator=row["creator"],
                source_url="", source_metadata=row["source_metadata"],
            )
            selections.append(clip)
        except (OSError, ValueError):
            unresolved.append((scene_id, "local-media-unavailable"))
    # Reuse F014's project scene/clip linkage checks, not a new approval path.
    project = build_final_project(snapshot["project_id"], scenes, selections, ".")
    return RestoredSession(
        snapshot["project_id"], scenes, tuple(project.selected_clips),
        tuple(unresolved), dict(snapshot["ui_state"]),
        restore_workflow_refs(snapshot["project_id"], snapshot["workflow_refs"]),
    )
