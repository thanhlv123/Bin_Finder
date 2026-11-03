"""Safe selected-media acquisition, probing and shot normalization."""
from dataclasses import dataclass, fields
from hashlib import sha256
import json
import math
from pathlib import Path
import subprocess
from time import monotonic, sleep
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from bin_finder.acquisition import verified_candidate_path
from bin_finder.acquisition.transport import validate_url
from bin_finder.models import CandidateRecord
from . import ProductionError
from .config import ProductionConfig
from .timeline import Shot
from .tts import NoRedirect

MAX_MEDIA_BYTES = 1024 * 1024 * 1024


def run_ffmpeg(arguments: list[str], cwd: Path | None = None) -> None:
    """Keep subprocess arguments separate and report bounded diagnostics."""
    try:
        result = subprocess.run(arguments, cwd=cwd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace")
    except OSError:
        raise ProductionError("FFmpeg executable could not be started") from None
    if result.returncode:
        # Input diagnostics can contain signed URLs; all inputs here must be local.
        raise ProductionError("FFmpeg failed: " + result.stderr[-2500:])


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    width: int
    height: int


def probe_media(path: Path, ffprobe: str = "ffprobe") -> MediaInfo:
    try:
        result = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-show_format",
                                 "-of", "json", str(path)], capture_output=True, check=True)
        payload = json.loads(result.stdout)
        video = next(stream for stream in payload["streams"] if stream["codec_type"] == "video")
        duration = float(video.get("duration") or payload["format"]["duration"])
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return MediaInfo(duration, int(video["width"]), int(video["height"]))
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError, StopIteration):
        raise ProductionError("Could not probe local video") from None


def rendition_url(candidate: dict) -> str:
    """Accept normalized R2 renditions and common raw provider representations."""
    metadata = candidate.get("source_metadata") or {}
    options = []
    for name in ("renditions", "video_files", "videos"):
        entries = metadata.get(name) or []
        if isinstance(entries, dict):
            entries = list(entries.values())
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            link = entry.get("url") or entry.get("link")
            try:
                width = int(entry.get("width") or 0)
                height = int(entry.get("height") or 0)
            except (TypeError, ValueError):
                continue
            if link and entry.get("file_type", "video/mp4") in ("video/mp4", "video/webm"):
                options.append((width >= 1920 and height >= 1080, width * height, str(link)))
    if options:
        return max(options)[2]
    urls = metadata.get("urls") or {}
    if isinstance(urls, dict):
        for name in ("mp4", "mp4_download", "download", "original"):
            if isinstance(urls.get(name), str) and urls[name]:
                return urls[name]
    return str(metadata.get("download_url") or metadata.get("original_url") or candidate.get("preview_url") or "")


def acquire_media(candidate: dict, config: ProductionConfig) -> Path:
    """Use verified F012 cache or stream HTTPS without redirects or proxies."""
    youtube_allowed = (config.youtube_reuse and candidate.get("license", {}).get("kind") == "youtube_reuse")
    if candidate.get("reference_only") or (candidate.get("provider", "").lower() == "youtube" and not youtube_allowed) or candidate.get("license", {}).get("usable_in_video") is not True:
        raise ProductionError("Media is not eligible for video")
    if candidate.get("provider") == "youtube" and youtube_allowed:
        path = Path(candidate.get("local_path") or "")
        if not path.is_file():
            raise ProductionError("YouTube local clip is missing")
        return path
    record_fields = {setting.name for setting in fields(CandidateRecord)}
    record = CandidateRecord(**{name: value for name, value in candidate.items() if name in record_fields})
    verified = verified_candidate_path(record)
    if verified:
        return verified
    link = rendition_url(candidate)
    try:
        validate_url(link)
        parsed = urlsplit(link)
        if parsed.scheme != "https":
            raise ValueError
    except (ValueError, TypeError):
        raise ProductionError("Selected media requires an HTTPS download URL") from None
    identity = json.dumps([candidate["provider"], candidate["source_id"], link])
    digest = sha256(identity.encode()).hexdigest()
    directory = Path(config.cache_dir) / "media"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{digest}.mp4"
    proof_path = destination.with_suffix(".json")
    if destination.exists() and proof_path.exists():
        try:
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            if sha256(destination.read_bytes()).hexdigest() == proof["sha256"]:
                return destination
        except (ValueError, KeyError):
            pass
    temporary = destination.with_suffix(".part")
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        deadline = monotonic() + 600
        for attempt in range(3):
            try:
                with opener.open(Request(link, headers={"User-Agent": "BinFinder/production"}), timeout=60) as response:
                    size = 0
                    digest_state = sha256()
                    with temporary.open("wb") as output:
                        while chunk := response.read(1024 * 1024):
                            if monotonic() > deadline:
                                raise ProductionError("Selected media download deadline exceeded")
                            size += len(chunk)
                            if size > MAX_MEDIA_BYTES:
                                raise ProductionError("Selected media exceeds download size limit")
                            digest_state.update(chunk)
                            output.write(chunk)
                break
            except HTTPError:
                raise
            except OSError:
                temporary.unlink(missing_ok=True)
                if attempt == 2:
                    raise
                delay = (2, 5)[attempt]
                if monotonic() + delay >= deadline:
                    raise ProductionError("Selected media download deadline exceeded")
                sleep(delay)
        probe_media(temporary, config.ffprobe)
        temporary.replace(destination)
        proof_path.write_text(json.dumps(dict(sha256=digest_state.hexdigest())), encoding="utf-8")
        return destination
    except (OSError, ValueError):
        raise ProductionError("Selected media download failed (HTTPS, no redirects)") from None
    finally:
        temporary.unlink(missing_ok=True)


def plan_clip(shot: Shot, candidate: dict, info: MediaInfo, duration: float,
              used_until: float = 0.0) -> None:
    """Prefer non-overlapping ranges; restart only when the source is exhausted."""
    if not math.isfinite(duration) or duration <= 0:
        raise ProductionError(f"Invalid shot duration: {shot.cue_id}")
    available = info.duration - used_until
    reused_from_start = used_until > 0 and available < 1
    if reused_from_start:
        used_until = 0.0
        available = info.duration
        shot.notes.append("Source reused from start")
    shot.speed = max(0.8, min(1.0, available / duration))
    required = min(available, duration * shot.speed)
    anchor = candidate.get("proposed_start")
    preferred = float(anchor) if anchor is not None else (info.duration - required) / 2
    if reused_from_start:
        preferred = 0.0
    if not math.isfinite(preferred):
        raise ProductionError(f"Invalid source anchor: {shot.cue_id}")
    shot.clip_in = max(used_until, min(preferred, info.duration - required))
    shot.clip_out = shot.clip_in + required
    if shot.speed < 1:
        shot.notes.append("Short source slowed to at least 0.8x")
    if required / shot.speed < duration - 0.001:
        shot.notes.append("Source exhausted after 0.8x slowdown; final frame extended with gentle zoom")
    if anchor is None and not reused_from_start:
        shot.notes.append("Center trim heuristic; visual best segment not analyzed")


def normalize_shot(shot: Shot, output: Path, duration: float, config: ProductionConfig) -> None:
    """Scale/crop, slow short clips, then animate any extended tail."""
    filters = [f"setpts=(PTS-STARTPTS)/{shot.speed}",
               f"scale={config.width}:{config.height}:force_original_aspect_ratio=increase",
               f"crop={config.width}:{config.height}", "setsar=1", f"fps={config.fps}",
               f"tpad=stop_mode=clone:stop_duration={duration}"]
    if config.ken_burns:
        filters.append(f"zoompan=z='min(1.035,1+on*0.000025)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={config.width}x{config.height}:fps={config.fps}")
    elif any("final frame" in note for note in shot.notes):
        shot.notes.append("ken_burns disabled: tail uses a static final frame")
    filters.extend([f"trim=duration={duration}", "setpts=PTS-STARTPTS", "format=yuv420p"])
    run_ffmpeg([config.ffmpeg, "-v", "error", "-y", "-ss", str(shot.clip_in), "-t",
                str(shot.clip_out - shot.clip_in), "-i", shot.local_path, "-an", "-vf", ",".join(filters),
                "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-threads", "2", str(output)])
