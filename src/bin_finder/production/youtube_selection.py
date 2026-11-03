"""Production preflight for YouTube transforms and cumulative source limits."""
from pathlib import Path

from bin_finder.footage.youtube_usage import read_usage, usage_context, violations
from . import ProductionError
from .youtube_transform import plan_transform, YouTubeTransformConfig


def _alternatives(entry: dict, footage_cues: dict) -> list[dict]:
    """Keep locked choices exact; auto choices may try their ranked alternatives."""
    cue = entry["cue"]
    alternatives = [entry["candidate"]]
    if cue.get("selection_origin") == "auto" and cue.get("status") != "locked":
        candidates = footage_cues[cue["cue_id"]]["candidates"]
        ordered_ids = [row["source_id"] for row in cue.get("ranked", [])]
        alternatives.extend(candidate for source_id in ordered_ids for candidate in candidates
                            if candidate["source_id"] == source_id and candidate is not entry["candidate"])
    return alternatives


def _acceptable(candidate: dict, cue_id: str, historical: list[dict], selected: list[dict],
                previous: dict | None, config: YouTubeTransformConfig) -> bool:
    """Check eligibility and a pure transform plan before speech or acquisition."""
    if candidate.get("reference_only") or candidate.get("license", {}).get("usable_in_video") is not True:
        return False
    if candidate.get("provider") != "youtube":
        return True
    evidence = candidate.get("youtube") or {}
    if candidate.get("license", {}).get("kind") != "youtube_reuse" or evidence.get("scene_drift"):
        return False
    if violations(evidence, usage_context(evidence, historical, selected), previous):
        return False
    try:
        resolution = str(candidate.get("resolution") or "1920x1080").split("x")
        width, height = map(int, resolution)
        plan_transform(evidence["regions"], cue_id, config, width, height)
    except (ProductionError, KeyError, ValueError, TypeError, ZeroDivisionError):
        return False
    return True


def prepare_youtube_selections(resolved: list[dict], footage_cues: dict, usage_path: str,
                               config: YouTubeTransformConfig | None = None) -> list[str]:
    """Resolve automatic fallbacks and preserve original source coordinates."""
    historical = read_usage(Path(usage_path)) if usage_path else []
    selected = []
    previous = None
    missing = []
    for entry in resolved:
        if entry["candidate"].get("provider") != "youtube":
            previous = None
            continue
        cue = entry["cue"]
        accepted = next((candidate for candidate in _alternatives(entry, footage_cues)
                         if _acceptable(candidate, cue["cue_id"], historical, selected, previous,
                                        config or YouTubeTransformConfig())), None)
        if accepted is None:
            missing.append(f"{cue['cue_id']}: YouTube transforms or source limits rejected candidates")
            continue
        original_id = entry["candidate"]["source_id"]
        entry["candidate"] = accepted
        cue["selected_source_id"] = accepted["source_id"]
        if original_id != accepted["source_id"]:
            cue.setdefault("youtube_rejections", []).append("YouTube transforms or source limits rejected " + original_id)
        previous = accepted.get("youtube") if accepted.get("provider") == "youtube" else None
        if previous:
            selected.append(previous)
    return missing
