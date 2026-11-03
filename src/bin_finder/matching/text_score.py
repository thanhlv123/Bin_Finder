"""Lexical metadata scoring, NOT visual evidence or embeddings.
TextScorer permits replacing this offline baseline with an embedding scorer later.
"""
from dataclasses import dataclass, asdict, is_dataclass
from typing import Protocol

from bin_finder.retrieval.lexical import tokenize, BM25Ranker, exact_phrase_scores

BM25_WEIGHT = 0.35
MUST_SHOW_WEIGHT = 0.25
ACTION_WEIGHT = 0.35
AVOID_PENALTY = 0.15
NO_ACTION_CAP = 0.39


@dataclass
class ScoredCandidate:
    candidate: dict
    text_score: float
    reasons: list[str]


class TextScorer(Protocol):
    def score_candidates(self, brief, cue_text, candidates) -> list[ScoredCandidate]: ...


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(_text(item) for item in value.values())
    return ""


def _candidate_text(candidate):
    metadata = candidate.get("source_metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    description = " ".join(_text(candidate.get(field)) for field in ("title", "description"))
    return description + " " + _text(metadata.get("tags")) + " " + _text(metadata.get("keywords"))


def _resolution(candidate):
    width = candidate.get("width", 0)
    height = candidate.get("height", 0)
    try:
        if not width:
            width, height = map(int, candidate.get("resolution", "").lower().split("x"))
    except (ValueError, TypeError):
        width, height = 0, 0
    return width, height


def _quality_bonus(candidate):
    width, height = candidate["width"], candidate["height"]
    resolution_bonus = 0.025 * bool(width and height and width >= 1920 and height >= 1080)
    duration_bonus = 0.025 * bool(4 <= (candidate.get("duration") or 0) <= 30)
    return resolution_bonus + duration_bonus


def score_candidates(brief, cue_text, candidates):
    brief_data = brief.to_dict() if hasattr(brief, "to_dict") else brief or {}
    rows = [asdict(candidate) if is_dataclass(candidate) else dict(candidate) for candidate in candidates]
    documents = [_candidate_text(candidate) for candidate in rows]
    query = " ".join(
        _text(brief_data.get(field)) for field in ("subject", "action", "setting", "must_show")
    ) or cue_text
    lexical_scores = BM25Ranker(documents).normalized_scores(query)
    phrase_scores = exact_phrase_scores(tuple(brief_data.get("must_show") or []), documents)
    action_words = [
        token for token in tokenize(brief_data.get("action", ""))
        if token not in {"the", "and", "with", "into", "through", "person", "people"}
    ]
    action_tokens = set(action_words)
    result = []
    for candidate, document, lexical_score, phrase_score in zip(
        rows, documents, lexical_scores, phrase_scores,
    ):
        tokens = set(tokenize(document))
        # Objects alone (e.g. "report") cannot establish that somebody reads it.
        action_score = 0
        if action_tokens and action_words[0] in tokens:
            action_score = len(action_tokens & tokens) / len(action_tokens)
        avoid_count = sum(
            len(set(tokenize(phrase)) & tokens) for phrase in brief_data.get("avoid", [])
        )
        candidate["width"], candidate["height"] = _resolution(candidate)
        quality_bonus = _quality_bonus(candidate)
        score = (
            BM25_WEIGHT * lexical_score
            + MUST_SHOW_WEIGHT * phrase_score
            + ACTION_WEIGHT * action_score
            + quality_bonus
            - AVOID_PENALTY * avoid_count
        )
        if action_tokens and not action_score:
            score = min(score, NO_ACTION_CAP)
        reasons = [
            f"BM25 metadata relevance: {lexical_score:.2f}",
            f"Must-show phrase coverage: {phrase_score:.2f}",
            f"Action evidence in metadata: {action_score:.2f}",
            f"Quality bonus: {quality_bonus:.3f}",
            f"Avoid penalty: {avoid_count * AVOID_PENALTY:.2f}",
        ]
        if candidate.get("reference_only") or candidate.get("provider") == "youtube":
            candidate["reference_only"] = True
            reasons.append("Reference only; never auto-select")
        result.append(ScoredCandidate(candidate, round(max(0, min(1, score)), 6), reasons))
    return sorted(result, key=lambda item: -item.text_score)
