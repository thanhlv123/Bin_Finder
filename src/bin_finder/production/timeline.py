"""Eligibility gate and voice-aligned production manifest."""
from dataclasses import asdict, dataclass, field
from urllib.parse import urlsplit, urlunsplit

from bin_finder.footage.service import FootagePlan
from bin_finder.matching.models import SelectionPlan

from . import MissingSelectionError, ProductionError
from .narration import Narration


def clean_url(value: str) -> str:
    """Exclude credentials, signed queries and fragments from manifests."""
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            return ""
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except ValueError:
        return ""


def resolve_selections(selection_plan: SelectionPlan, footage_plan: FootagePlan,
                       allow_suggested: bool = False) -> list[dict]:
    """Fail all missing or forbidden choices before any side effects."""
    footage_cues = {cue["cue_id"]: cue for cue in footage_plan.cues}
    resolved = []
    missing = []
    for cue in selection_plan.cues:
        source_id = cue.get("selected_source_id")
        origin = "selected"
        if not source_id and allow_suggested:
            source_id = cue.get("suggested_source_id")
            origin = "suggested"
        candidates = footage_cues.get(cue["cue_id"], {}).get("candidates", [])
        candidate = next((item for item in candidates if item["source_id"] == source_id), None)
        eligible = candidate and candidate.get("provider", "").lower() != "youtube"
        eligible = eligible and not candidate.get("reference_only")
        eligible = eligible and candidate.get("license", {}).get("usable_in_video") is True
        if not eligible:
            missing.append(f"{cue['cue_id']}: {cue['text']}")
        else:
            resolved.append(dict(cue=cue, candidate=candidate, origin=origin))
    if missing:
        raise MissingSelectionError("Missing eligible footage selections:\n" + "\n".join(missing))
    if not resolved:
        raise ProductionError("Selection plan has no cues")
    return resolved


@dataclass
class Shot:
    cue_id: str
    text: str
    start: float
    end: float
    source_id: str
    provider: str
    local_path: str
    origin: str
    license: dict
    clip_in: float = 0.0
    clip_out: float = 0.0
    speed: float = 1.0
    effects: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    block_index: int = 0


@dataclass
class Timeline:
    shots: list[Shot]
    duration: float
    words: list[dict]
    version: str = "production_v1"
    timings: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    subtitles: bool = True
    music_path: str | None = None
    end_hold: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Timeline":
        values = dict(payload)
        values["shots"] = [Shot(**shot) for shot in values["shots"]]
        return cls(**values)


def build_timeline(selection_plan: SelectionPlan, footage_plan: FootagePlan, narration: Narration,
                   allow_suggested: bool = False) -> Timeline:
    """Start shots on first words and hold the last shot beyond the WAV tail."""
    resolved = resolve_selections(selection_plan, footage_plan, allow_suggested)
    duration = narration.duration + narration.end_hold
    shots = []
    for index, entry in enumerate(resolved):
        cue = entry["cue"]
        candidate = entry["candidate"]
        start = narration.cue_starts[cue["cue_id"]]
        end = narration.cue_starts[resolved[index + 1]["cue"]["cue_id"]] if index + 1 < len(resolved) else duration
        if end <= start:
            raise ProductionError(f"Nonpositive cue duration: {cue['cue_id']}")
        license_info = {name: candidate["license"][name] for name in
                        ("provider", "source_id", "title", "creator", "creator_url", "source_url",
                         "license_name", "license_url", "attribution_required", "usable_in_video")
                        if name in candidate["license"]}
        for name in ("source_url", "creator_url", "license_url"):
            if name in license_info:
                license_info[name] = clean_url(license_info[name])
        shots.append(Shot(cue["cue_id"], cue["text"], start, end, candidate["source_id"],
                          candidate["provider"], "", entry["origin"], license_info,
                          block_index=narration.cue_block_indices.get(cue["cue_id"], 0)))
    return Timeline(shots, duration, [asdict(word) for word in narration.words])
