"""Voice-preserving transition assembly, overlays and audio mixing."""
from functools import lru_cache
from pathlib import Path
import re
import subprocess
from typing import Callable

from . import ProductionError
from .config import ProductionConfig
from .icons import write_subscribe_icon
from .media import normalize_shot, run_ffmpeg
from .subtitles import write_subtitles
from .timeline import Timeline


def _filter_script_option(version: str) -> str:
    """Date-based Git builds and FFmpeg 7+ support option values from files."""
    match = re.search(r"ffmpeg version (\d+)", version)
    if not match:
        raise ProductionError("Could not determine FFmpeg version")
    return "-/filter_complex" if int(match.group(1)) >= 7 else "-filter_complex_script"


@lru_cache(maxsize=None)
def _ffmpeg_filter_script_option(ffmpeg: str) -> str:
    """Probe each configured executable only once."""
    try:
        result = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", check=True)
    except (OSError, subprocess.CalledProcessError):
        raise ProductionError("Could not determine FFmpeg version") from None
    return _filter_script_option(result.stdout)


def filter_script_arguments(ffmpeg: str, path: Path) -> list[str]:
    """Keep filter graphs in files while supporting older FFmpeg releases."""
    return [_ffmpeg_filter_script_option(ffmpeg), str(path)]


def transition_durations(timeline: Timeline, config: ProductionConfig) -> list[float]:
    """Each outgoing shot gets extra frames for its next transition."""
    durations = []
    for previous, current in zip(timeline.shots, timeline.shots[1:]):
        different = previous.source_id != current.source_id
        duration = min(config.xfade_sec, (previous.end - previous.start) / 2,
                       (current.end - current.start) / 2) if different else 0.0
        durations.append(duration)
    return [*durations, 0.0]


def assembly_filter(timeline: Timeline, transitions: list[float]) -> tuple[str, str]:
    """Offsets equal cue starts; outgoing overlap is added before joining."""
    filters = [f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS[v{index}]" for index in range(len(timeline.shots))]
    previous = "v0"
    for index in range(1, len(timeline.shots)):
        output = f"join{index}"
        duration = transitions[index - 1]
        if duration:
            filters.append(f"[{previous}][v{index}]xfade=transition=fade:duration={duration:.6f}:offset={timeline.shots[index].start:.6f}[{output}]")
        else:
            absolute_end = timeline.shots[index].end + transitions[index]
            filters.append(f"[{previous}][v{index}]concat=n=2:v=1:a=0,trim=duration={absolute_end:.6f},setpts=PTS-STARTPTS[{output}]")
        previous = output
    return ";\n".join(filters), previous


def icon_times(duration: float, config: ProductionConfig) -> list[float]:
    """Start the first appearance at 30 seconds, then repeat periodically."""
    times = []
    cursor = 30.0
    while cursor < duration:
        times.append(cursor)
        cursor += config.subscribe_interval_sec
    return times


def plan_effects(timeline: Timeline, config: ProductionConfig) -> list[float]:
    """Use one schedule for manifest flags and the actual audio mix."""
    appearances = icon_times(timeline.duration, config) if config.subscribe_icon else []
    last_whoosh = float("-inf")
    boundaries = []
    for index, shot in enumerate(timeline.shots):
        boundary = index > 0 and shot.block_index != timeline.shots[index - 1].block_index
        if boundary:
            boundaries.append(shot.start)
        whoosh = bool(boundary and config.whoosh_path and shot.start - last_whoosh >= config.whoosh_min_gap_sec)
        if whoosh:
            last_whoosh = shot.start
        pop = bool(config.pop_path and any(start < shot.end and start + config.subscribe_duration_sec > shot.start for start in appearances))
        shot.effects.update(whoosh=whoosh, pop=pop, leak=bool(boundary and config.leak_path))
    return boundaries


def icon_decoration() -> str:
    """Prefer a bold Windows font, with FFmpeg's default as a fallback."""
    font_option = ""
    for font_name in ("segoeuib.ttf", "arialbd.ttf"):
        font_path = Path("C:/Windows/Fonts") / font_name
        if font_path.is_file():
            escaped_path = font_path.as_posix().replace(":", r"\:")
            font_option = f"fontfile='{escaped_path}':"
            break
    return (f",drawtext={font_option}text=LIKE:fontsize=46:fontcolor=white:x=5+(180-text_w)/2:y=(110-text_h)/2"
            f",drawtext={font_option}text=SUBSCRIBE:fontsize=46:fontcolor=white:x=200+(325-text_w)/2:y=(110-text_h)/2")


def render_video(timeline: Timeline, narration_path: Path, output: Path, work_dir: Path,
                 config: ProductionConfig, progress: Callable[[str], None] = print) -> None:
    """Render silent intermediates, join, then burn overlays and mix audio."""
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    transitions = transition_durations(timeline, config)
    shot_paths = []
    for index, shot in enumerate(timeline.shots):
        progress(f"Render shot {index + 1}/{len(timeline.shots)}")
        start = shot.start if index else 0.0
        duration = shot.end - start + transitions[index]
        shot.effects.update(xfade=transitions[index])
        path = work_dir / f"shot_{index:05d}.mp4"
        normalize_shot(shot, path, duration, config)
        shot_paths.append(path)
    graph, label = assembly_filter(timeline, transitions)
    graph_path = work_dir / "assembly.ffgraph"
    graph_path.write_text(graph, encoding="utf-8")
    joined = work_dir / "joined.mp4"
    arguments = [config.ffmpeg, "-v", "error", "-y", "-filter_complex_threads", "1"]
    for path in shot_paths:
        arguments.extend(["-i", str(path)])
    arguments.extend(filter_script_arguments(config.ffmpeg, graph_path))
    arguments.extend(["-map", f"[{label}]", "-an", "-t",
                      str(timeline.duration), "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                      "-pix_fmt", "yuv420p", "-threads", "2", str(joined)])
    run_ffmpeg(arguments)
    progress("Mix narration, music, effects and overlays")
    _mix(timeline, narration_path, joined, output, work_dir, config)


def _mix(timeline: Timeline, narration_path: Path, joined: Path, output: Path,
         work_dir: Path, config: ProductionConfig) -> None:
    """Build a local-only filter script for captions, icons and mixed audio."""
    arguments = [config.ffmpeg, "-v", "error", "-y", "-filter_complex_threads", "1",
                 "-i", str(joined), "-i", str(narration_path.resolve())]
    filters = [f"[1:a]apad,atrim=duration={timeline.duration},asetpts=PTS-STARTPTS,aresample=48000[voice]"]
    audio_labels = ["voice"]
    next_input = 2
    if config.music_path:
        arguments.extend(["-stream_loop", "-1", "-i", str(Path(config.music_path).resolve())])
        # Nominal reduction at -18 dB voice against a -36 dB threshold.
        ratio = min(20, max(1, 18 / max(0.9, 18 + config.duck_db)))
        filters.extend(["[voice]asplit=2[narration][control]",
                        f"[{next_input}:a]volume={config.music_db}dB,atrim=duration={timeline.duration},aresample=48000[music]",
                        f"[music][control]sidechaincompress=threshold=0.015849:ratio={ratio}:attack=20:release=350[ducked]"])
        audio_labels = ["narration", "ducked"]
        next_input += 1
    boundaries = plan_effects(timeline, config)
    events = []
    for shot in timeline.shots:
        if shot.effects["whoosh"]:
            events.append((config.whoosh_path, shot.start, -10))
    if config.subscribe_icon and config.pop_path:
        events.extend((config.pop_path, start, -10) for start in icon_times(timeline.duration, config))
    for event_index, (path, start, decibels) in enumerate(events):
        arguments.extend(["-i", str(Path(path).resolve())])
        label = f"sfx{event_index}"
        delay = round(start * 1000)
        filters.append(f"[{next_input}:a]aresample=48000,volume={decibels}dB,adelay={delay}:all=1[{label}]")
        audio_labels.append(label)
        next_input += 1
    filters.append("".join(f"[{label}]" for label in audio_labels) +
                   f"amix=inputs={len(audio_labels)}:normalize=0:duration=longest,atrim=duration={timeline.duration}[audio]")
    video_filters = []
    if config.subtitles:
        write_subtitles(timeline.words, work_dir / "captions.ass", config.width, config.height)
        video_filters.append("ass=filename=captions.ass")
    filters.append("[0:v]" + (",".join(video_filters) if video_filters else "null") + "[decorated]")
    video_label = "decorated"
    appearances = icon_times(timeline.duration, config) if config.subscribe_icon else []
    if appearances:
        icon_path = Path(config.subscribe_icon_path).resolve() if config.subscribe_icon_path else work_dir / "subscribe.png"
        if not config.subscribe_icon_path:
            write_subscribe_icon(icon_path)
        arguments.extend(["-loop", "1", "-framerate", str(config.fps), "-i", str(icon_path)])
        decoration = ""
        if not config.subscribe_icon_path:
            decoration = icon_decoration()
        outputs = "".join(f"[icon{index}]" for index in range(len(appearances)))
        filters.append(f"[{next_input}:v]format=rgba{decoration},split={len(appearances)}{outputs}")
        for index, start in enumerate(appearances):
            end = min(timeline.duration, start + config.subscribe_duration_sec)
            fade = min(0.3, (end - start) / 2)
            filters.append(f"[icon{index}]fade=t=in:st={start}:d={fade}:alpha=1,fade=t=out:st={end - fade}:d={fade}:alpha=1[faded{index}]")
            filters.append(f"[{video_label}][faded{index}]overlay=x=W-w-50:y=H-h-170:enable='between(t,{start},{end})'[overlay{index}]")
            video_label = f"overlay{index}"
        next_input += 1
    if config.leak_path:
        for index, start in enumerate(boundaries):
            arguments.extend(["-stream_loop", "-1", "-i", str(Path(config.leak_path).resolve())])
            end = min(timeline.duration, start + 1.2)
            filters.append(f"[{next_input}:v]trim=duration={end - start},setpts=PTS-STARTPTS+{start}/TB,scale={config.width}:{config.height},format=rgba,colorkey=0x000000:0.15:0.2,colorchannelmixer=aa=0.5[leak{index}]")
            filters.append(f"[{video_label}][leak{index}]overlay=eof_action=pass:enable='gte(t,{start})*lt(t,{end})'[leaked{index}]")
            video_label = f"leaked{index}"
            next_input += 1
    graph_path = work_dir / "mix.ffgraph"
    graph_path.write_text(";\n".join(filters), encoding="utf-8")
    arguments.extend(filter_script_arguments(config.ffmpeg, graph_path))
    arguments.extend(["-map", f"[{video_label}]", "-map", "[audio]",
                      "-t", str(timeline.duration), "-r", str(config.fps), "-c:v", "libx264", "-preset", "fast",
                      "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                      "-movflags", "+faststart", "-threads", "2", str(output.resolve())])
    run_ffmpeg(arguments, work_dir)
