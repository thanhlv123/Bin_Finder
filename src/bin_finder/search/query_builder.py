from __future__ import annotations

import re

from bin_finder.models import SceneRecord


_WORD_RE = re.compile(r"[A-Za-z0-9À-ỹ]+", re.UNICODE)
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "with", "for", "from",
    "is", "are", "was", "were", "his", "her", "their", "him", "them", "another", "before",
}


def _compact_words(text: str, limit: int = 10) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for token in _WORD_RE.findall(text):
        lowered = token.lower()
        if len(lowered) < 2 or lowered in _STOP or lowered in seen:
            continue
        seen.add(lowered)
        words.append(token)
        if len(words) >= limit:
            break
    return words


def build_scene_queries(scene: SceneRecord, max_queries: int = 3) -> list[str]:
    """Build deterministic discovery queries without an LLM dependency."""
    ctx = scene.context
    candidates: list[str] = []
    if ctx.keywords:
        candidates.extend(ctx.keywords)
    subject_action_location = [
        *(ctx.subject[:1] if ctx.subject else ()),
        *(ctx.action[:1] if ctx.action else ()),
        *(ctx.location[:1] if ctx.location else ()),
    ]
    if subject_action_location:
        candidates.append(" ".join(subject_action_location))
    compact = " ".join(_compact_words(scene.english_text, limit=10))
    if compact:
        candidates.append(compact)

    unique: list[str] = []
    seen: set[str] = set()
    for query in candidates:
        normalized = " ".join(query.split()).strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            unique.append(normalized)
        if len(unique) >= max_queries:
            break
    return unique or [scene.english_text.strip()[:100]]
