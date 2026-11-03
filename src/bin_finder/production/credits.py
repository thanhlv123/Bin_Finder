"""Footage and local audio attribution without provider request metadata."""

import json
from pathlib import Path

from .config import ProductionConfig
from .timeline import Timeline


def write_credits(timeline: Timeline, config: ProductionConfig, output: Path) -> None:
    """List unique sources, cue origins and neighboring audio license files."""
    lines = ["Footage credits", ""]
    source_ids = list(dict.fromkeys(shot.source_id for shot in timeline.shots))
    for source_id in source_ids:
        shots = [shot for shot in timeline.shots if shot.source_id == source_id]
        info = shots[0].license
        lines.append(f"{shots[0].provider}: {info.get('title', source_id)} — {info.get('creator') or 'Unknown creator'}")
        lines.append(f"Source: {info.get('source_url', '')}")
        lines.append(f"License: {info.get('license_name', '')} {info.get('license_url', '')}")
        lines.append("Cues: " + ", ".join(shot.cue_id + (" [suggested]" if shot.origin == "suggested" else "") for shot in shots))
        lines.append("")
    youtube_shots = [shot for shot in timeline.shots if shot.provider == "youtube"]
    if youtube_shots:
        lines.extend(["YouTube", ""])
        for shot in youtube_shots:
            info = shot.youtube
            lines.append(f"{shot.license.get('title', shot.source_id)} \u2014 {info.get('channel', '')}")
            lines.append(f"https://www.youtube.com/watch?v={info['video_id']}&t={info['start']:g}s")
            lines.append(f"Segment: {info['start']:g}\u2013{info['end']:g} seconds")
            lines.append("Transforms: " + ", ".join(shot.transforms))
            lines.append(f"Zoom: {shot.zoom:g}; rotate: {shot.rotate:g}; mirrored: {shot.mirrored}; blurred regions: {json.dumps(shot.blurred_regions)}")
            lines.append("")
    for name in ("music_path", "whoosh_path", "pop_path", "leak_path"):
        value = getattr(config, name)
        if not value:
            continue
        path = Path(value)
        lines.append(f"{name.removesuffix('_path')}: {path.name}")
        license_path = path.parent / "LICENSE.txt"
        if license_path.is_file():
            lines.append(license_path.read_text(encoding="utf-8"))
        metadata_path = path.parent / "credits.json"
        if metadata_path.is_file():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            entry = metadata.get(path.name, {}) if isinstance(metadata, dict) else {}
            if isinstance(entry, dict):
                for key in ("title", "author", "creator", "license", "url", "credit"):
                    if key in entry:
                        lines.append(f"{key}: {entry[key]}")
            elif isinstance(entry, str):
                lines.append(entry)
    lines.append("Voice: VoiceStudio (The Documentarian)")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
