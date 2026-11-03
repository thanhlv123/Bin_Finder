"""Produce an approved selection plan as a voice-aligned MP4."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Callable

from bin_finder.footage.service import FootagePlan
from bin_finder.matching.decisions import apply_decisions
from bin_finder.matching.models import SelectionPlan
from . import MissingSelectionError, ProductionError
from .config import ProductionConfig
from .credits import write_credits
from .media import acquire_media, plan_clip, probe_media
from .narration import build_narration
from .render import render_video, transition_durations
from .timeline import build_timeline, resolve_selections
from .tts import SpeechEngine, VoiceStudioEngine


def parser() -> argparse.ArgumentParser:
    """Expose headless production and explicit suggestion overrides."""
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("selection", type=Path)
    arguments.add_argument("--footage", type=Path, required=True)
    arguments.add_argument("-o", "--output", type=Path, required=True)
    arguments.add_argument("--decisions", type=Path)
    arguments.add_argument("--allow-suggested", action="store_true")
    arguments.add_argument("--limit-cues", type=int)
    arguments.add_argument("--work-dir", type=Path)
    arguments.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments.add_argument("--music", type=Path)
    arguments.add_argument("--no-subtitles", action="store_true")
    arguments.add_argument("--no-icon", action="store_true")
    arguments.add_argument("--youtube-reuse", action=argparse.BooleanOptionalAction, default=None)
    arguments.add_argument("--dry-run", action="store_true")
    return arguments


def main(argv: list[str] | None = None, *, engine: SpeechEngine | None = None,
         media_loader: Callable = acquire_media, media_probe: Callable = probe_media,
         renderer: Callable = render_video) -> int:
    """Inject speech/media boundaries for entirely offline CLI tests."""
    arguments = parser().parse_args(argv)
    try:
        return produce(arguments, engine, media_loader, media_probe, renderer)
    except MissingSelectionError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (ProductionError, ValueError, OSError, KeyError, TypeError) as error:
        # External transport exceptions are sanitized at their respective boundaries.
        message = str(error) if isinstance(error, ProductionError) else "Invalid production input or configuration"
        print(message, file=sys.stderr)
        return 1


def produce(arguments: argparse.Namespace, engine: SpeechEngine | None, media_loader: Callable,
            media_probe: Callable, renderer: Callable) -> int:
    """Gate selections, generate narration, prepare media and publish outputs."""
    selection = SelectionPlan.from_dict(json.loads(arguments.selection.read_text(encoding="utf-8")))
    footage = FootagePlan.from_dict(json.loads(arguments.footage.read_text(encoding="utf-8")))
    if arguments.decisions:
        selection = apply_decisions(selection, json.loads(arguments.decisions.read_text(encoding="utf-8")))
    if arguments.limit_cues is not None:
        if arguments.limit_cues <= 0:
            raise ProductionError("--limit-cues must be positive")
        selection.cues = selection.cues[:arguments.limit_cues]
    from bin_finder.footage.config import FootageConfig
    config = ProductionConfig.load(arguments.project_root)
    reuse = arguments.youtube_reuse
    if reuse is None:
        reuse = FootageConfig.load(arguments.project_root).youtube_reuse
    config = replace(config, youtube_reuse=reuse)
    resolved = resolve_selections(selection, footage, arguments.allow_suggested, reuse, config.youtube_transform)
    if arguments.dry_run:
        for entry in resolved:
            print(f"{entry['cue']['cue_id']}: {entry['candidate']['source_id']} ({entry['origin']}) — {entry['cue']['text']}")
        print(f"Dry run: {len(resolved)} cues; no speech or media acquired")
        return 0
    overrides = {}
    if arguments.music:
        overrides["music_path"] = str(arguments.music.resolve())
    if arguments.no_subtitles:
        overrides["subtitles"] = False
    if arguments.no_icon:
        overrides["subscribe_icon"] = False
    config = replace(config, **overrides)
    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    work_dir = (arguments.work_dir or output.parent / (output.stem + "_work")).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    narration = build_narration(selection.cues, engine or VoiceStudioEngine(config), config)
    tts_seconds = perf_counter() - started
    narration_path = work_dir / "narration.wav"
    narration_path.write_bytes(narration.wav_bytes)
    timeline = build_timeline(selection, footage, narration, arguments.allow_suggested, reuse, config.youtube_transform)
    timeline.subtitles = config.subtitles
    timeline.music_path = config.music_path
    timeline.end_hold = config.end_hold
    transitions = transition_durations(timeline, config)
    started = perf_counter()
    paths = {}
    source_positions = {}
    for index, (shot, entry) in enumerate(zip(timeline.shots, resolved)):
        print(f"Acquire clip {index + 1}/{len(resolved)}")
        source_key = (shot.provider, shot.source_id)
        if source_key not in paths:
            paths[source_key] = Path(media_loader(entry["candidate"], config)).resolve()
        shot.local_path = str(paths[source_key])
        info = media_probe(paths[source_key], config.ffprobe)
        if shot.provider == "youtube":
            from .youtube_transform import transform_shot
            transform_shot(shot, work_dir / f"youtube_{index:05d}.mp4", config, info.width, info.height)
        duration = shot.end - (shot.start if index else 0) + transitions[index]
        plan_clip(shot, entry["candidate"], info, duration, source_positions.get(source_key, 0))
        source_positions[source_key] = shot.clip_out
        if index and timeline.shots[index - 1].source_id == shot.source_id:
            shot.notes.append("Explicit adjacent source reuse retained; source ranges do not overlap")
    media_seconds = perf_counter() - started
    started = perf_counter()
    renderer(timeline, narration_path, output, work_dir, config)
    timeline.timings.update(tts=tts_seconds, media=media_seconds, render=perf_counter() - started)
    credits_path = output.parent / "credits.txt"
    manifest_path = output.parent / "production.json"
    write_credits(timeline, config, credits_path)
    manifest_path.write_text(json.dumps(timeline.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    if reuse and footage.youtube_usage_path:
        from bin_finder.footage.youtube_usage import save_usage
        save_usage(Path(footage.youtube_usage_path), [shot.youtube for shot in timeline.shots if shot.provider == "youtube"])
    suggested = sum(shot.origin == "suggested" for shot in timeline.shots)
    print(f"Complete: {len(timeline.shots)} cues, {timeline.duration:.2f}s; selected={len(timeline.shots) - suggested}, suggested={suggested}")
    print("Step seconds: " + ", ".join(f"{name}={seconds:.2f}" for name, seconds in timeline.timings.items()))
    print(f"MP4: {output}\nCredits: {credits_path}\nTimeline: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
