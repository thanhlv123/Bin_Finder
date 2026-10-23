"""ZB-01 experimental contract for editorial scene-to-footage search intents.

Read-only, dependency-free and opt-in. Z5-inspired design concepts, not vendor code.
Does NOT create AI interpretations or modify GUI, scene records, VLM, or providers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


class InvalidIntent(ValueError):
    """An untrusted editorial plan failed bounded validation."""


def _text(value: object, *, max_chars: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise InvalidIntent("not-text")
    out = " ".join(value.split())
    if len(out) > max_chars or (required and not out):
        raise InvalidIntent("text-out-of-bounds")
    if any(ord(c) < 32 or ord(c) == 127 for c in out):
        raise InvalidIntent("control-character")
    return out


def _list(value: object, *, count: int, max_chars: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > count:
        raise InvalidIntent("invalid-list")
    strings = tuple(_text(item, max_chars=max_chars, required=True) for item in value)
    if len(set(s.casefold() for s in strings)) != len(strings):
        raise InvalidIntent("duplicate-list-item")
    return strings


@dataclass(frozen=True)
class StoryCapsule:
    summary: str
    central_message: str
    arc: str

    @classmethod
    def from_mapping(cls, obj: Mapping[str, object]) -> "StoryCapsule":
        if not isinstance(obj, Mapping):
            raise InvalidIntent("capsule-not-object")
        return cls(
            summary=_text(obj.get("summary"), max_chars=500, required=True),
            central_message=_text(obj.get("central_message"), max_chars=250, required=True),
            arc=_text(obj.get("arc"), max_chars=500),
        )


@dataclass(frozen=True)
class SceneSearchIntent:
    scene_id: str
    narration_text: str
    visual_goal: str
    required_entities: tuple[str, ...]
    must_show: tuple[str, ...]
    must_not_show: tuple[str, ...]
    queries: tuple[str, ...]
    uncertainty: str
    provenance: str

    @classmethod
    def from_mapping(
        cls, obj: Mapping[str, object], *, scene_id: str,
        narration_text: str, full_script: str,
    ) -> "SceneSearchIntent":
        if not isinstance(obj, Mapping):
            raise InvalidIntent("intent-not-object")
        if _text(scene_id, max_chars=100, required=True) != obj.get("scene_id"):
            raise InvalidIntent("scene-id-mismatch")
        if _text(narration_text, max_chars=1500, required=True) != _text(
            obj.get("narration_text"), max_chars=1500, required=True
        ):
            raise InvalidIntent("scene-text-mismatch")
        visual_goal = _text(obj.get("visual_goal"), max_chars=300, required=True)
        required = _list(obj.get("required_entities", ()), count=6, max_chars=100)
        must_show = _list(obj.get("must_show", ()), count=6, max_chars=150)
        must_not_show = _list(obj.get("must_not_show", ()), count=6, max_chars=150)
        queries = _list(obj.get("queries", ()), count=3, max_chars=160)
        if not queries:
            raise InvalidIntent("missing-queries")
        if not isinstance(full_script, str) or len(full_script) > 50000:
            raise InvalidIntent("invalid-script")
        # Named mandatory entities must be grounded in the input script and
        # preserved in each query. Semantic claims still need editorial review.
        for ent in required:
            if ent.casefold() not in full_script.casefold():
                raise InvalidIntent("unsupported-required-entity")
            if any(ent.casefold() not in q.casefold() for q in queries):
                raise InvalidIntent("required-entity-lost")
        provenance = _text(obj.get("provenance", ""), max_chars=50, required=True)
        if provenance not in ("script", "editor_review"):
            raise InvalidIntent("bad-provenance")
        return cls(
            scene_id=scene_id,
            narration_text=narration_text,
            visual_goal=visual_goal,
            required_entities=required,
            must_show=must_show,
            must_not_show=must_not_show,
            queries=queries,
            uncertainty=_text(obj.get("uncertainty", ""), max_chars=300),
            provenance=provenance,
        )


def validated_queries_or_fallback(
    proposed: Mapping[str, object], *, scene_id: str, narration_text: str,
    full_script: str, fallback_queries: Sequence[str],
) -> tuple[str, ...]:
    """Pure fail-safe boundary. Caller supplies the existing legacy queries."""
    try:
        intent = SceneSearchIntent.from_mapping(
            proposed, scene_id=scene_id, narration_text=narration_text,
            full_script=full_script,
        )
        return intent.queries
    except (InvalidIntent, TypeError, AttributeError):
        return tuple(fallback_queries)[:3]


def proposed_queries_for_scene(
    scene, proposed: Mapping[str, object] | None,
    *, full_script: str, max_queries: int = 3,
) -> list[str]:
    """Explicit opt-in adapter; absent/invalid plans retain legacy behavior.

    No AI interpretation is produced here. A separately validated planner
    or editor must provide the mapping. No GUI or provider is wired in ZB-01.
    """
    from bin_finder.search.query_builder import build_scene_queries

    legacy = build_scene_queries(scene, max_queries=max_queries)
    if proposed is None or not 1 <= max_queries <= 3:
        return legacy
    result = validated_queries_or_fallback(
        proposed,
        scene_id=scene.scene_id,
        narration_text=scene.english_text,
        full_script=full_script,
        fallback_queries=legacy,
    )
    return list(result[:max_queries])
