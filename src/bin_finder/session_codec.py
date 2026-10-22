"""F016 versioned allowlist codec for local project sessions."""
from __future__ import annotations

import math
import os
import re
from pathlib import Path
from bin_finder.models import SceneRecord, SceneContext, SelectedClipRecord

FORMAT = "bin_finder_session_v1"
CONTEXT = tuple(SceneContext.__dataclass_fields__)


class SessionError(ValueError):
    pass


def safe_text(value, limit=50000):
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise SessionError("invalid-text")
    if "://" in value and "?" in value:
        raise SessionError("query-url-refused")
    return value


def _snapshot_text(value, limit=50000):
    text = safe_text(value, limit)
    forbidden = ("authorization:", "bearer ", "api_key", "access_token",
                 "client_secret", "secret=", "token=", "password=", "signature=")
    if any(marker in text.lower() for marker in forbidden):
        raise SessionError("unsafe-snapshot-text")
    for name, secret in os.environ.items():
        if (name.startswith("BIN_FINDER_") and
                ("KEY" in name or "SECRET" in name) and
                secret and secret in text):
            raise SessionError("unsafe-snapshot-text")
    return text


def scene_to_data(scene):
    if not isinstance(scene, SceneRecord):
        raise SessionError("invalid-scene")
    if type(scene.order) is not int or scene.order < 0:
        raise SessionError("invalid-order")
    if not math.isfinite(scene.target_duration) or scene.target_duration <= 0:
        raise SessionError("invalid-duration")
    return {
        "scene_id": _snapshot_text(scene.scene_id, 128),
        "order": scene.order,
        "english_text": _snapshot_text(scene.english_text),
        "vietnamese_text": _snapshot_text(scene.vietnamese_text),
        "target_duration": scene.target_duration,
        "context": {key: [_snapshot_text(x, 1024) for x in getattr(scene.context, key)]
                    for key in CONTEXT},
    }


def scene_from_data(data):
    if not isinstance(data, dict) or set(data) != {
            "scene_id", "order", "english_text", "vietnamese_text",
            "target_duration", "context"}:
        raise SessionError("invalid-scene")
    ctx = data["context"]
    if not isinstance(ctx, dict) or set(ctx) != set(CONTEXT):
        raise SessionError("invalid-context")
    for value in ctx.values():
        if not isinstance(value, list) or len(value) > 100:
            raise SessionError("invalid-context")
    normalized = scene_to_data(SceneRecord(
        data["scene_id"], data["order"], data["english_text"],
        data["vietnamese_text"], data["target_duration"], "unselected",
        SceneContext(**{key: tuple(ctx[key]) for key in CONTEXT})))
    return SceneRecord(**{**normalized, "context": SceneContext(
        **{key: tuple(normalized["context"][key]) for key in CONTEXT})})




# Only these final-approval fields may survive a process restart.
# Remote source URLs and arbitrary provider payloads are intentionally excluded.
SELECTION_FIELDS = (
    "clip_id", "scene_id", "scene_order", "provider", "source_id", "title",
    "local_file", "start", "end", "duration", "semantic_score", "vlm_score",
    "final_score", "rights_status", "creator", "source_metadata",
)
SELECTION_META = (
    "media_sha256", "duplicate_group", "proposal_unit_id",
    "verification_provider", "license_basis", "usage_authorization",
    "asset_id", "creator_id", "rendition",
)


def _selection_text(value, limit=2048):
    text = safe_text(value, limit)
    forbidden = ("authorization:", "bearer ", "api_key", "access_token",
                 "secret=", "token=", "password=", "signature=")
    if any(marker in text.lower() for marker in forbidden):
        raise SessionError("unsafe-selection-text")
    for name, secret in os.environ.items():
        if (name.startswith("BIN_FINDER_") and
                ("KEY" in name or "SECRET" in name) and
                secret and secret in text):
            raise SessionError("unsafe-selection-text")
    return text


def _finite(value, minimum, maximum):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise SessionError("invalid-selection-number")
    if not minimum <= value <= maximum:
        raise SessionError("invalid-selection-number")
    return float(value)


def validate_selection_data(data):
    """Schema validation is not approval: restore must re-hash media separately."""
    if not isinstance(data, dict) or set(data) != set(SELECTION_FIELDS):
        raise SessionError("unvalidated-references")
    if not isinstance(data["source_metadata"], dict):
        raise SessionError("unvalidated-references")
    metadata = data["source_metadata"]
    if set(metadata) - set(SELECTION_META) or "media_sha256" not in metadata:
        raise SessionError("unvalidated-references")
    normalized_meta = {key: _selection_text(value) for key, value in metadata.items()}
    if not re.fullmatch(r"[0-9a-f]{64}", normalized_meta["media_sha256"]):
        raise SessionError("invalid-media-sha256")
    if ("usage_authorization" in normalized_meta and
            normalized_meta["usage_authorization"] not in
            {"unknown", "user_authorized_acquisition"}):
        raise SessionError("invalid-authorization-state")
    clip_id = _selection_text(data["clip_id"], 80)
    if not re.fullmatch(r"clip_[0-9a-f]{64}", clip_id):
        raise SessionError("invalid-clip-id")
    scene_id = _selection_text(data["scene_id"], 128)
    if not scene_id or type(data["scene_order"]) is not int or data["scene_order"] < 0:
        raise SessionError("invalid-selection-scene")
    path = _selection_text(data["local_file"], 4096)
    if not Path(path).is_absolute() or "\x00" in path:
        raise SessionError("invalid-selection-path")
    start = _finite(data["start"], 0, 86400 * 365)
    end = _finite(data["end"], 0, 86400 * 365)
    duration = _finite(data["duration"], 3.5, 7.0)
    if end <= start or abs((end - start) - duration) > 0.001:
        raise SessionError("invalid-selection-range")
    normalized = {
        "clip_id": clip_id,
        "scene_id": scene_id,
        "scene_order": data["scene_order"],
        "provider": _selection_text(data["provider"], 128),
        "source_id": _selection_text(data["source_id"], 512),
        "title": _selection_text(data["title"]),
        "local_file": path,
        "start": start,
        "end": end,
        "duration": duration,
        "semantic_score": _finite(data["semantic_score"], 0, 1),
        "vlm_score": _finite(data["vlm_score"], 0, 1),
        "final_score": _finite(data["final_score"], 0, 1),
        "rights_status": _selection_text(data["rights_status"], 128),
        "creator": _selection_text(data["creator"]),
        "source_metadata": normalized_meta,
    }
    if not normalized["provider"] or not normalized["source_id"]:
        raise SessionError("missing-source-identity")
    return normalized


def selection_to_data(clip):
    """Only an existing explicit F014 SelectedClipRecord can be serialized."""
    if not isinstance(clip, SelectedClipRecord):
        raise SessionError("final-record-required")
    metadata = clip.source_metadata
    if not isinstance(metadata, dict):
        raise SessionError("unvalidated-references")
    row = {key: getattr(clip, key) for key in SELECTION_FIELDS
           if key != "source_metadata"}
    row["source_metadata"] = {key: metadata[key] for key in SELECTION_META
                              if key in metadata}
    return validate_selection_data(row)


def validate_snapshot(payload):
    if not isinstance(payload, dict) or set(payload) != {
            "format", "project_id", "scenes", "final_selections",
            "ui_state", "workflow_refs"} or payload["format"] != FORMAT:
        raise SessionError("invalid-format")
    if not isinstance(payload["scenes"], list) or len(payload["scenes"]) > 1000:
        raise SessionError("invalid-scenes")
    scenes = [scene_to_data(scene_from_data(item)) for item in payload["scenes"]]
    ids = [scene["scene_id"] for scene in scenes]
    if len(set(ids)) != len(ids):
        raise SessionError("duplicate-scenes")
    if not isinstance(payload["final_selections"], list) or len(payload["final_selections"]) > len(scenes):
        raise SessionError("unvalidated-references")
    selections = [validate_selection_data(item) for item in payload["final_selections"]]
    scene_orders = {scene["scene_id"]: scene["order"] for scene in scenes}
    selected_ids = [item["scene_id"] for item in selections]
    if (len(set(selected_ids)) != len(selected_ids) or
            any(item["scene_id"] not in scene_orders or
                item["scene_order"] != scene_orders[item["scene_id"]]
                for item in selections)):
        raise SessionError("unvalidated-references")
    if payload["workflow_refs"]:
        raise SessionError("unvalidated-references")
    if not isinstance(payload["ui_state"], dict) or set(payload["ui_state"]) - {
            "script_text", "output_dir", "current_scene_id"}:
        raise SessionError("invalid-ui")
    return {"format": FORMAT, "project_id": _snapshot_text(payload["project_id"], 128),
            "scenes": scenes, "final_selections": selections, "workflow_refs": [],
            "ui_state": {key: _snapshot_text(value) for key, value in payload["ui_state"].items()}}
