"""Keyless discovery and bounded, visually verified YouTube acquisition."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from hashlib import sha256
import json
import logging
from pathlib import Path
import re
import subprocess
from typing import Any, Callable
from urllib.parse import quote_plus, urlsplit
from urllib.request import Request, build_opener, ProxyHandler

from bin_finder.matching.text_score import score_candidates
from bin_finder.models import CandidateRecord
from bin_finder.retrieval.lexical import tokenize
from bin_finder.verification.ollama_vlm import _NoRedirect
from .config import FootageConfig
from .credits import LicenseInfo
from .youtube_usage import read_usage, violations
from .youtube_vlm import YouTubeFrameJudge, VlmResponseError, VlmUnavailable


class YouTubeClips:
    """Inject subprocess, HTTP and visual boundaries for offline replay."""

    def __init__(self, config: FootageConfig, runner: Callable | None = None,
                 opener: Any | None = None, judge: Any | None = None) -> None:
        self.config = config
        self.runner = runner or subprocess.run
        self.opener = opener or build_opener(ProxyHandler({}), _NoRedirect())
        self.judge = judge or YouTubeFrameJudge(config.youtube_vlm_model)
        self.reset_run()
        self.cache = Path(config.cache_dir).resolve()
        self.cache.mkdir(parents=True, exist_ok=True)
        self.usage_path = Path(config.usage_dir or ".") / "youtube-usage.json"
        self.usage = read_usage(self.usage_path)

    def reset_run(self) -> None:
        """Reset the circuit breaker for one footage run."""
        self.consecutive_errors = 0
        self.disabled_error = ""
        self.inspected_frames = 0

    def _inspect(self, brief: object, cue_text: str, image: bytes, thumbnail: bool = True) -> dict:
        """Count all VLM calls, including acquisition checks."""
        self.inspected_frames += 1
        try:
            verdict = self.judge.inspect(brief, cue_text, image, thumbnail=thumbnail)
        except (VlmUnavailable, VlmResponseError) as error:
            self.consecutive_errors += 1
            if self.consecutive_errors >= 3:
                self.disabled_error = (
                    f"YouTube VLM lỗi liên tiếp ({type(error).__name__}), "
                    f"kiểm tra Ollama và model {self.config.youtube_vlm_model}"
                )
                logging.getLogger(__name__).error(self.disabled_error)
            raise
        self.consecutive_errors = 0
        return verdict

    def _run(self, arguments: list[str]) -> bytes:
        """Run a bounded process without retaining external diagnostics."""
        result = self.runner(arguments, capture_output=True, timeout=300)
        if result.returncode:
            raise ValueError("YouTube subprocess failed")
        return result.stdout if isinstance(result.stdout, bytes) else result.stdout.encode()

    def _yt(self, arguments: list[str]) -> bytes:
        """Ignore global downloader configuration for reproducible local runs."""
        return self._run([self.config.yt_dlp, "--ignore-config", "--quiet", "--no-warnings", *arguments])

    def _search_ids(self, queries: list[str]) -> list[str]:
        """Find bounded video identities without a YouTube API key."""
        identities = []
        for query in queries:
            url = "https://www.youtube.com/results?search_query=" + quote_plus(query)
            if self.config.cc_only:
                url += "&sp=EgIwAQ%253D%253D"
            body = self._yt(["--flat-playlist", "--playlist-end", str(self.config.videos_per_cue * 2), "-j", url])
            for line in body.splitlines():
                entry = json.loads(line)
                entries = entry.get("entries", [entry])
                for item in entries:
                    video_id = str(item.get("id", ""))
                    duration = item.get("duration")
                    try:
                        duration = float(duration) if duration is not None else None
                    except (ValueError, TypeError):
                        continue
                    if "/shorts/" in str(item.get("url", "")) or duration is not None and not 30 <= float(duration) <= 10800:
                        continue
                    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", video_id) and video_id not in identities:
                        identities.append(video_id)
            if len(identities) >= self.config.videos_per_cue:
                break
        return identities[:self.config.videos_per_cue]

    def _prepare(self, video_id: str) -> dict | None:
        """Cache info and needed storyboard grids in parallel across videos."""
        try:
            path = self.cache / f"{video_id}.info.json"
            if path.exists():
                cached = json.loads(path.read_text(encoding="utf-8"))
                frames = [(float(timestamp), Path(frame)) for timestamp, frame in cached.get("cached_frames", [])]
                if (cached.get("frames_per_video") == self.config.frames_per_video and frames
                        and all(frame.is_file() for timestamp, frame in frames)):
                    if self.config.cc_only and "creative commons" not in str(cached.get("license", "")).lower():
                        return None
                    return {"info": cached, "frames": frames}
            info = json.loads(self._yt(["--skip-download", "-j", "https://www.youtube.com/watch?v=" + video_id]))
            if info.get("id") != video_id:
                return None
            if not 30 <= float(info["duration"]) <= 10800 or info.get("is_short") is True or "/shorts/" in str(info.get("webpage_url", "")):
                return None
            if self.config.cc_only and "creative commons" not in str(info.get("license", "")).lower():
                return None
            formats = [item for item in info["formats"] if str(item.get("format_id", "")).startswith("sb")]
            storyboard = max(formats, key=lambda item: int(item.get("width") or 0) * int(item.get("height") or 0))
            frames = self._tiles(video_id, info, storyboard)
            # Never persist signed playback/storyboard URLs or transport headers.
            safe_info = {name: info.get(name) for name in ("id", "title", "description", "channel", "channel_id", "duration", "license", "width", "height")}
            safe_info["frames_per_video"] = self.config.frames_per_video
            safe_info["cached_frames"] = [(timestamp, str(frame)) for timestamp, frame in frames]
            path.write_text(json.dumps(safe_info), encoding="utf-8")
            return {"info": safe_info, "frames": frames}
        except Exception:
            return None

    def _grid(self, url: str, destination: Path) -> None:
        """Download a bounded image from the storyboard CDN without redirects."""
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not (parsed.hostname or "").endswith(".ytimg.com") or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("Invalid storyboard host")
        with self.opener.open(Request(url, headers={"User-Agent": "BinFinder/footage"}), timeout=30) as response:
            data = response.read(16 * 1024 * 1024 + 1)
        if not data or len(data) > 16 * 1024 * 1024:
            raise ValueError("Invalid storyboard size")
        destination.write_bytes(data)

    def _tiles(self, video_id: str, info: dict, storyboard: dict) -> list[tuple[float, Path]]:
        """Sample evenly spaced cells, excluding the first and last five percent."""
        count = int(storyboard["rows"]) * int(storyboard["columns"])
        elapsed = 0.0
        cells = []
        for index, fragment in enumerate(storyboard["fragments"]):
            grid = self.cache / f"{video_id}.{storyboard['format_id']}.{index}.jpg"
            fragment["local_grid"] = str(grid)
            duration = float(fragment.get("duration") or count / float(storyboard["fps"]))
            for cell in range(count):
                timestamp = elapsed + cell * duration / count
                if float(info["duration"]) * 0.05 <= timestamp <= float(info["duration"]) * 0.95:
                    cells.append((timestamp, grid, fragment, cell))
            elapsed += duration
        if not cells:
            return []
        if len(cells) <= self.config.frames_per_video:
            indices = list(range(len(cells)))
        elif self.config.frames_per_video == 1:
            indices = [len(cells) // 2]
        else:
            indices = sorted({round(index * (len(cells) - 1) / (self.config.frames_per_video - 1))
                              for index in range(min(self.config.frames_per_video, len(cells)))})
        frames = []
        for index in indices:
            timestamp, grid, fragment, cell = cells[index]
            if not grid.exists():
                self._grid(fragment["url"], grid)
            frame = self.cache / f"{video_id}.{storyboard['format_id']}.{index}.tile.jpg"
            width = int(storyboard["width"])
            height = int(storyboard["height"])
            row, column = divmod(cell, int(storyboard["columns"]))
            if not frame.exists():
                self._run([self.config.ffmpeg, "-v", "error", "-y", "-i", str(grid), "-vf",
                           f"crop={width}:{height}:{column * width}:{row * height},scale=480:-2", "-frames:v", "1", str(frame)])
            frames.append((timestamp, frame))
        return frames

    def _candidate(self, cue: object, info: dict, start: float, end: float, path: Path, verdict: dict) -> dict:
        """Emit the shared candidate schema plus verified source coordinates."""
        video_id = info["id"]
        source_id = f"youtube:{video_id}:{start:.3f}-{end:.3f}"
        url = "https://www.youtube.com/watch?v=" + video_id
        record = CandidateRecord(candidate_id=f"{cue.cue_id}:{source_id}", scene_id=cue.cue_id,
                                 provider="youtube", source_id=source_id, title=info.get("title") or video_id,
                                 duration=end - start, score=verdict["score"], rights_status="youtube_reuse",
                                 resolution=f"{info.get('width') or 1920}x{info.get('height') or 1080}",
                                 source_url=url, creator=info.get("channel") or "", description=info.get("description") or "")
        license_info = asdict(LicenseInfo("youtube", source_id, record.title, record.creator, "", url,
                                        "YouTube reuse (project opt-in)", "", True, True,
                                        "Project opt-in; transformations do not grant copyright permission.",
                                        kind="youtube_reuse", requires_transform=True))
        youtube = {"video_id": video_id, "channel": record.creator, "channel_id": info.get("channel_id") or record.creator,
                   "url": url, "start": start, "end": end, "storyboard_score": verdict["score"],
                   "regions": verdict["regions"], "scene_drift": False}
        return {**asdict(record), "license": license_info, "reference_only": False,
                "local_path": str(path), "youtube": youtube}

    def _clip(self, cue: object, brief: object, info: dict, timestamp: float, verdict: dict) -> dict | None:
        """Acquire one window, verify real frames, and keep a silent short clip."""
        duration = min(5.0, max(3.0, cue.est_duration_sec))
        window = max(duration, self.config.window_seconds)
        start = max(0.0, min(timestamp - window / 2, float(info["duration"]) - window))
        end = min(float(info["duration"]), start + window)
        identity = sha256(f"{info['id']}:{start:.3f}:{end:.3f}".encode()).hexdigest()
        wide = self.cache / f"{identity}.mp4"
        if not wide.exists():
            self._yt(["--download-sections", f"*{start:.3f}-{end:.3f}", "--force-keyframes-at-cuts",
                      "-f", "bv*[height<=1080][ext=mp4]/bv*[height<=1080]", "--remux-video", "mp4",
                      "-o", str(wide), "https://www.youtube.com/watch?v=" + info["id"]])
        offset = max(0.0, min(timestamp - start - duration / 2, end - start - duration))
        regions = list(verdict["regions"])
        for sample in (offset, offset + duration / 2):
            image = self._run([self.config.ffmpeg, "-v", "error", "-ss", str(sample), "-i", str(wide),
                               "-frames:v", "1", "-vf", "scale=960:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"])
            check = self._inspect(brief, cue.text, image, thumbnail=False)
            if check["reject"] or check["score"] < max(0.5, 0.78 * verdict["score"]):
                raise ValueError("scene_drift")
            regions.extend(check["regions"])
        clip = self.cache / f"{identity}.{offset:.3f}.{duration:.3f}.clip.mp4"
        if not clip.exists():
            self._run([self.config.ffmpeg, "-v", "error", "-y", "-ss", str(offset), "-i", str(wide),
                       "-t", str(duration), "-map", "0:v:0", "-an", "-c:v", "libx264", str(clip)])
        unique_regions = [json.loads(value) for value in dict.fromkeys(json.dumps(region, sort_keys=True) for region in regions)]
        candidate = self._candidate(cue, info, start + offset, start + offset + duration, clip,
                                    {**verdict, "regions": unique_regions})
        from .youtube_usage import usage_context
        return candidate if not violations(candidate["youtube"], usage_context(candidate["youtube"], self.usage, [])) else None

    def search(self, cue: object, brief: object, queries: list[str]) -> tuple[list[dict], list[str]]:
        """Report one progress line even when the YouTube circuit is open."""
        self.inspected_frames = 0
        self.searched_videos = 0
        candidates = []
        try:
            if self.disabled_error:
                return [], [self.disabled_error]
            candidates, warnings = self._search(cue, brief, queries)
            return candidates, warnings
        finally:
            print(
                f"YouTube {cue.cue_id}: {self.searched_videos} video, "
                f"{self.inspected_frames} khung soi, {len(candidates)} clip",
                flush=True,
            )

    def _search(self, cue: object, brief: object, queries: list[str]) -> tuple[list[dict], list[str]]:
        """Skip individual failures and keep warnings free of remote diagnostics."""
        warnings = []
        try:
            identities = self._search_ids(queries)
            self.searched_videos = len(identities)
        except Exception:
            return [], ["YouTube search failed"]
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            prepared = list(executor.map(self._prepare, identities))
        videos = []
        for video_id, result in zip(identities, prepared):
            if result is None:
                warnings.append(f"YouTube {video_id}: info/storyboard unavailable")
            else:
                videos.append(result)
        metadata = [{"title": result["info"].get("title"), "description": str(result["info"].get("description")) + " " + str(result["info"].get("channel")), "source_metadata": {}, "video": result} for result in videos]
        ranked = score_candidates(brief, cue.text, metadata)
        candidates = []
        for item in ranked:
            if item.text_score <= 0:
                query_tokens = set(tokenize(" ".join(queries) + " " + cue.text))
                metadata_tokens = set(tokenize(str(item.candidate.get("title")) + " " + str(item.candidate.get("description"))))
                if not query_tokens.intersection(metadata_tokens):
                    continue
            result = item.candidate["video"]
            try:
                frames = []
                for timestamp, frame in result["frames"]:
                    verdict = self._inspect(brief, cue.text, frame.read_bytes())
                    if not verdict["reject"] and verdict["score"] >= self.config.youtube_min_frame_score:
                        frames.append((timestamp, verdict))
                for timestamp, verdict in sorted(frames, key=lambda item: -item[1]["score"]):
                    try:
                        candidate = self._clip(cue, brief, result["info"], timestamp, verdict)
                        if candidate:
                            candidates.append(candidate)
                            break
                    except (VlmUnavailable, VlmResponseError) as error:
                        warnings.append(f"YouTube {result['info']['id']}: {type(error).__name__}")
                        if self.disabled_error:
                            return candidates, warnings + [self.disabled_error]
                    except Exception:
                        warnings.append(f"YouTube {result['info']['id']}: clip rejected (scene_drift/regions/acquisition)")
            except (VlmUnavailable, VlmResponseError) as error:
                warnings.append(f"YouTube {result['info']['id']}: {type(error).__name__}")
                if self.disabled_error:
                    return candidates, warnings + [self.disabled_error]
            except Exception:
                warnings.append(f"YouTube {result['info']['id']}: frame inspection failed")
        return candidates, warnings
