"""Sequential selection; metadata and thumbnail checks never authorize acquisition."""
from hashlib import sha256
import json
from time import perf_counter

from .models import SelectionPlan
from .text_score import score_candidates
from .vlm_score import OllamaThumbnailJudge, ThumbnailFetcher, VlmUnavailable, VlmResponseError

TEXT_WEIGHT = 0.4
VISUAL_WEIGHT = 0.6

_ROW_FIELDS = (
    "source_id", "provider", "title", "thumbnail_url", "preview_url", "source_url",
    "duration", "width", "height", "license", "reference_only",
)


def _rank_cue(cue, brief, config, judge, fetch, unavailable):
    start = perf_counter()
    scored = score_candidates(brief, cue["text"], cue["candidates"])[:config.top_k]
    text_seconds = perf_counter() - start
    start = perf_counter()
    ranked = []
    thumbnail_flags = []
    visual_count = 0
    calls = 0
    for item in scored:
        candidate = item.candidate
        verdict = None
        can_judge = (
            config.vlm_enabled
            and not unavailable
            and not candidate.get("reference_only")
            and candidate.get("thumbnail_url")
            and visual_count < config.vlm_top_n
        )
        if can_judge:
            visual_count += 1
            image = fetch(candidate["thumbnail_url"], config)
            if not image and fetch.last_error not in thumbnail_flags:
                thumbnail_flags.append(fetch.last_error)
            if image:
                try:
                    calls += 1
                    verdict = judge.judge(brief, cue["text"], candidate, image)
                except (VlmUnavailable, OSError):
                    unavailable = True
                except VlmResponseError:
                    pass
        row = {field: candidate.get(field) for field in _ROW_FIELDS}
        final_score = item.text_score
        if verdict:
            final_score = round(TEXT_WEIGHT * item.text_score + VISUAL_WEIGHT * verdict.score, 6)
        row.update(
            text_score=item.text_score,
            vlm=verdict.to_dict() if verdict else None,
            final_score=final_score,
            reasons=list(item.reasons),
        )
        if not verdict:
            row["reasons"].append("VLM missing; lexical evidence only")
        ranked.append(row)
    visual_seconds = perf_counter() - start
    ranked.sort(key=lambda row: -row["final_score"])
    return ranked, text_seconds, visual_seconds, calls, unavailable, thumbnail_flags


def _eligible(row, config):
    verdict = row["vlm"]
    if config.vlm_enabled and not verdict:
        return False
    if config.vlm_enabled and verdict["score"] < config.min_vlm_score:
        return False
    if verdict and verdict["match"] not in ("match", "partial"):
        return False
    return (
        not row["reference_only"]
        and row["text_score"] >= config.min_text_score
        and row["final_score"] >= config.auto_select_threshold
        and (row.get("license") or {}).get("usable_in_video", True)
    )


def _pick(ranked, config, previous_source, used_sources, providers):
    eligible = [row for row in ranked if _eligible(row, config)]
    if config.no_adjacent_reuse:
        eligible = [row for row in eligible if row["source_id"] != previous_source]
        fresh = [row for row in eligible if row["source_id"] not in used_sources]
        if fresh:
            eligible = fresh
    if not eligible:
        return None
    selected = eligible[0]
    recent_providers = providers[-config.source_cooldown:]
    rotate_provider = (
        len(providers) >= config.source_cooldown
        and all(provider == selected["provider"] for provider in recent_providers)
    )
    if rotate_provider:
        for alternative in eligible:
            different_provider = alternative["provider"] != selected["provider"]
            score_gap = selected["final_score"] - alternative["final_score"]
            if different_provider and score_gap <= 0.1:
                selected = alternative
                break
    return selected


def _unresolved_reason(ranked, config):
    if not ranked:
        return "no_candidates"
    if all(row["reference_only"] for row in ranked):
        return "only_reference"
    if config.vlm_enabled and not any(row["vlm"] for row in ranked):
        return "vlm_missing"
    if config.vlm_enabled and any(
        row["vlm"] and row["vlm"]["match"] in ("match", "partial")
        and row["vlm"]["score"] < config.min_vlm_score
        for row in ranked
    ):
        return "low_visual_confidence"
    if any(row["vlm"] and row["vlm"]["match"] == "no_match" for row in ranked):
        return "vlm_no_match"
    return "low_confidence"


def _stats(cues, text_seconds, visual_seconds, calls, unavailable):
    cue_count = len(cues)
    return dict(
        auto_selected=sum(cue["status"] == "auto_selected" for cue in cues),
        needs_review=sum(cue["status"] == "needs_review" for cue in cues),
        no_candidates=sum(not cue["ranked"] for cue in cues),
        text_seconds=text_seconds,
        vlm_seconds=visual_seconds,
        text_seconds_per_cue=text_seconds / cue_count if cue_count else 0,
        vlm_seconds_per_cue=visual_seconds / cue_count if cue_count else 0,
        vlm_calls=calls,
        vlm_unavailable=unavailable,
    )


def select_footage(footage_plan, brief_plan, config, judge=None, fetch=None):
    briefs = {brief.cue_id: brief for brief in brief_plan.briefs}
    fetch = ThumbnailFetcher(fetch)
    if config.vlm_enabled and judge is None:
        judge = OllamaThumbnailJudge()
    unavailable = False
    cues = []
    used_sources = set()
    providers = []
    calls = 0
    text_seconds = 0.0
    visual_seconds = 0.0
    for cue in footage_plan.cues:
        ranked, text_elapsed, visual_elapsed, cue_calls, unavailable, thumbnail_flags = _rank_cue(
            cue, briefs.get(cue["cue_id"]), config, judge, fetch, unavailable,
        )
        text_seconds += text_elapsed
        visual_seconds += visual_elapsed
        calls += cue_calls
        flags = list(thumbnail_flags)
        if not config.vlm_enabled or not any(row["vlm"] for row in ranked):
            flags.append("vlm_missing")
        if unavailable:
            flags.append("vlm_unavailable")
        if any(
            row["vlm"] and (row["vlm"]["needs_motion_check"] or row["vlm"]["match"] == "uncertain")
            for row in ranked
        ):
            flags.append("needs_motion_check")
        previous_source = cues[-1]["selected_source_id"] if cues else None
        selected = _pick(ranked, config, previous_source, used_sources, providers)
        if selected:
            if selected["source_id"] in used_sources:
                flags.extend(["source_reuse_fallback", "overlap_not_verified"])
            used_sources.add(selected["source_id"])
        else:
            reason = _unresolved_reason(ranked, config)
            if reason not in flags:
                flags.append(reason)
        providers.append(selected["provider"] if selected else None)
        confidence = ranked[0]["final_score"] if ranked else 0
        if selected:
            confidence = selected["final_score"]
        cues.append(dict(
            cue_id=cue["cue_id"],
            text=cue["text"],
            ranked=ranked,
            selected_source_id=selected["source_id"] if selected else None,
            suggested_source_id=ranked[0]["source_id"] if ranked else None,
            selection_origin="auto" if selected else None,
            confidence=confidence,
            status="auto_selected" if selected else "needs_review",
            flags=flags,
        ))
    stats = _stats(cues, text_seconds, visual_seconds, calls, unavailable)
    stats["thumbnail_fetched"] = fetch.thumbnail_fetched
    stats["thumbnail_failed"] = fetch.thumbnail_failed
    footage_json = json.dumps(
        footage_plan.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    )
    digest = sha256(footage_json.encode()).hexdigest()
    return SelectionPlan(
        "selection_plan_v1", digest, footage_plan.brief_sha256, footage_plan.script_sha256,
        config.summary(), cues, stats,
    )
