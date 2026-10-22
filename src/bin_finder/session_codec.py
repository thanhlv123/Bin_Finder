"""F016 versioned allowlist codec for local project sessions."""
from __future__ import annotations

import math
from dataclasses import asdict
from bin_finder.models import SceneRecord, SceneContext

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


def scene_to_data(scene):
    if not isinstance(scene, SceneRecord):
        raise SessionError("invalid-scene")
    if type(scene.order) is not int or scene.order < 0:
        raise SessionError("invalid-order")
    if not math.isfinite(scene.target_duration) or scene.target_duration <= 0:
        raise SessionError("invalid-duration")
    return {
        "scene_id": safe_text(scene.scene_id, 128),
        "order": scene.order,
        "english_text": safe_text(scene.english_text),
        "vietnamese_text": safe_text(scene.vietnamese_text),
        "target_duration": scene.target_duration,
        "context": {key: [safe_text(x, 1024) for x in getattr(scene.context, key)]
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
    if payload["final_selections"] or payload["workflow_refs"]:
        raise SessionError("unvalidated-references")
    if not isinstance(payload["ui_state"], dict) or set(payload["ui_state"]) - {
            "script_text", "output_dir", "current_scene_id"}:
        raise SessionError("invalid-ui")
    return {"format": FORMAT, "project_id": safe_text(payload["project_id"], 128),
            "scenes": scenes, "final_selections": [], "workflow_refs": [],
            "ui_state": {key: safe_text(value) for key, value in payload["ui_state"].items()}}
