"""ZB-01 experimental contract for editorial scene-to-footage search intents.

Read-only, dependency-free and opt-in. Z5-inspired design concepts, not vendor code.
Does NOT create AI interpretations or modify GUI, scene records, VLM, or providers.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence


class InvalidIntent(ValueError):
    """An untrusted editorial plan failed bounded validation."""


EVIDENCE_TYPES = frozenset({
    "direct", "contextual", "editorial_metaphor", "weak_indirect", "no_match",
})
# Deliberately compact: these words are grammatical glue, not scene subjects.
_STOPWORDS = frozenset((
    "a", "an", "and", "as", "at", "be", "been", "but", "by", "can", "for",
    "from", "had", "has", "have", "in", "into", "is", "it", "its", "just",
    "of", "on", "or", "out", "past", "that", "the", "their", "them", "there",
    "these", "this", "those", "through", "to", "was", "were", "where",
    "which", "while", "with", "would", "who", "up", "off", "still",
))


def _stem(word: str) -> str:
    """Minimal comparison normalization, not a language-understanding model."""
    word = word.casefold()
    if len(word) > 5 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > 4 and word.endswith("es"):
        word = (word[:-2] if word.endswith(
            ("ches", "shes", "sses", "xes", "zzes")
        ) else word[:-1])
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    # Controlled demonym variant. Common tags use either Cuba or Cuban.
    if word == "cuban":
        return "cuba"
    return word


def _focus_terms(text: str) -> set[str]:
    return {
        _stem(token) for token in re.findall(r"[a-zA-Z0-9]+", text)
        if len(token) >= 4 and token.casefold() not in _STOPWORDS
    }


def _validate_scene_focus(anchor: str, narration: str, queries: tuple[str, ...]) -> None:
    """Conservative lexical anti-drift gate; does not claim semantic accuracy.

    At least one anchored cue per query, and two distinct grounded cues across
    the candidate set where the anchor contains two or more cues. Models can
    abstain instead of hallucinating a visual for an abstract statement.
    """
    # Model often removes stopwords from a copied excerpt (e.g. "machines
    # repaired patched" from "machines that have been repaired and patched").
    # Require all meaningful anchor tokens in source order; never accept an
    # injected off-scene subject just because it appears in the story overview.
    anchor_tokens = [
        _stem(token) for token in re.findall(r"[a-zA-Z0-9]+", anchor)
        if len(token) >= 4 and token.casefold() not in _STOPWORDS
    ]
    narration_tokens = [
        _stem(token) for token in re.findall(r"[a-zA-Z0-9]+", narration)
        if len(token) >= 4 and token.casefold() not in _STOPWORDS
    ]
    if not anchor_tokens:
        raise InvalidIntent("empty-scene-focus")
    # Do not let the model anchor only on a broad place name while discussing
    # local goods/prices/actions. Require >=2 distinct cues when available.
    if len(set(narration_tokens)) >= 2 and len(set(anchor_tokens)) < 2:
        raise InvalidIntent("weak-scene-anchor")
    iterator = iter(narration_tokens)
    if not all(any(word == cue for word in iterator) for cue in anchor_tokens):
        raise InvalidIntent("scene-anchor-not-in-narration")
    focused = set(anchor_tokens)
    # Explicit valid abstention has no searches to ground. Still validate its
    # anchor against the actual current narration.
    if not queries:
        return
    all_matched: set[str] = set()
    for query in queries:
        overlap = focused.intersection(_focus_terms(query))
        if not overlap:
            raise InvalidIntent("query-lost-scene-focus")
        all_matched.update(overlap)
    if len(focused) >= 2 and len(all_matched) < 2:
        raise InvalidIntent("insufficient-scene-focus")


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
    evidence_type: str = "contextual"
    scene_anchor: str = ""

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
        evidence = obj.get("evidence_type", "contextual")
        if not isinstance(evidence, str) or evidence not in EVIDENCE_TYPES:
            raise InvalidIntent("invalid-evidence-type")
        # New model contract requires a verbatim current-scene anchor. Legacy
        # editor plans without these optional research fields stay compatible.
        anchor = ""
        if "evidence_type" in obj:
            anchor = _text(obj.get("scene_anchor"), max_chars=160, required=True)
        if evidence == "no_match":
            if queries or required or must_show:
                raise InvalidIntent("no-match-has-search-requirements")
            if not _text(obj.get("uncertainty", ""), max_chars=300, required=True):
                raise InvalidIntent("no-match-without-reason")
        elif not queries:
            raise InvalidIntent("missing-queries")
        if not isinstance(full_script, str) or len(full_script) > 50000:
            raise InvalidIntent("invalid-script")
        if anchor:
            _validate_scene_focus(anchor, narration_text, queries)
        # Script-anchored mandatory terms are preserved in *every* query.
        # Compare whole normalized tokens rather than raw substrings, so
        # Chevrolet/Chevrolets and Cuba/Cuban are accepted, but invented
        # locations and dropped entities are still rejected.
        script_terms = tuple(_stem(t) for t in re.findall(r"[a-zA-Z0-9]+", full_script))
        for ent in required:
            ent_terms = tuple(_stem(t) for t in re.findall(r"[a-zA-Z0-9]+", ent))
            if not ent_terms:
                raise InvalidIntent("unsupported-required-entity")
            def contains_phrase(haystack: tuple[str, ...]) -> bool:
                return any(
                    haystack[i:i + len(ent_terms)] == ent_terms
                    for i in range(len(haystack) - len(ent_terms) + 1)
                )
            if not contains_phrase(script_terms):
                raise InvalidIntent("unsupported-required-entity")
            if any(
                not contains_phrase(tuple(_stem(t) for t in re.findall(r"[a-zA-Z0-9]+", q)))
                for q in queries
            ):
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
            evidence_type=evidence,
            scene_anchor=anchor,
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
