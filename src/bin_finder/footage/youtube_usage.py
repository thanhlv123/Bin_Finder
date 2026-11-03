"""Shared project limits for selected YouTube source intervals."""
import json
from pathlib import Path


def violations(candidate: dict, selected: list[dict], previous: dict | None = None) -> list[str]:
    """Report source limits using original video coordinates."""
    video_id = candidate.get("video_id")
    channel_id = candidate.get("channel_id") or candidate.get("channel")
    if not video_id or not channel_id:
        return ["youtube_identity"]
    same_video = [item for item in selected if item.get("video_id") == video_id]
    same_channel = [item for item in selected if (item.get("channel_id") or item.get("channel")) == channel_id]
    reasons = []
    if previous and previous.get("video_id") == video_id:
        reasons.append("youtube_adjacent")
    if len(same_video) >= 3:
        reasons.append("youtube_video_limit")
    if len(same_channel) >= 10:
        reasons.append("youtube_channel_limit")
    if any(max(float(candidate["start"]), float(item["start"])) - min(float(candidate["end"]), float(item["end"])) < 60 for item in same_video):
        reasons.append("youtube_gap")
    return reasons


def read_usage(path: Path) -> list[dict]:
    """Fail closed on a malformed project ledger."""
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise ValueError("Invalid YouTube usage ledger")
    return payload


def save_usage(path: Path, selected: list[dict]) -> None:
    """Atomically persist unique accepted intervals, making resume idempotent."""
    existing = read_usage(path)
    identities = {(item["video_id"], item["start"], item["end"]) for item in existing}
    for item in selected:
        identity = (item["video_id"], item["start"], item["end"])
        if identity not in identities:
            existing.append({name: item[name] for name in ("video_id", "channel_id", "channel", "start", "end")})
            identities.add(identity)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    temporary.replace(path)


def usage_context(candidate: dict, historical: list[dict], current: list[dict]) -> list[dict]:
    """Re-rendering an accepted interval does not spend another ledger slot."""
    def identity(item: dict) -> tuple:
        return item.get("video_id"), item.get("start"), item.get("end")
    current_keys = {identity(item) for item in current}
    return [item for item in historical if identity(item) != identity(candidate) and identity(item) not in current_keys] + current
