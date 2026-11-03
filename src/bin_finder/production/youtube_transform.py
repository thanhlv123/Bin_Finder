"""Deterministic YouTube crop, region blur, mirror and rotation planning."""
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from hashlib import sha256
import math
import random

from . import ProductionError

if TYPE_CHECKING:
    from .config import ProductionConfig
    from .timeline import Shot


@dataclass(frozen=True)
class YouTubeTransformConfig:
    min_zoom: float = 1.08
    max_zoom: float = 1.4
    mirror: bool = True
    rotate_degrees: float = 3.0

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.min_zoom, self.max_zoom, self.rotate_degrees)):
            raise ValueError("Invalid YouTube transform")
        if not 1 <= self.min_zoom <= self.max_zoom <= 3 or not 1 <= self.rotate_degrees <= 3 or type(self.mirror) is not bool:
            raise ValueError("Invalid YouTube transform limits")


def rotation_zoom(degrees: float, aspect: float = 16 / 9) -> float:
    """Uniform zoom needed to keep all rotated output corners covered."""
    angle = math.radians(abs(degrees))
    return math.cos(angle) + max(aspect, 1 / aspect) * math.sin(angle)


def intersects(first: list[float], second: list[float]) -> bool:
    """Treat touching edges as disjoint normalized rectangles."""
    return (max(first[0], second[0]) < min(first[0] + first[2], second[0] + second[2]) - 1e-8
            and max(first[1], second[1]) < min(first[1] + first[3], second[1] + second[3]) - 1e-8)


def crop_avoiding(regions: list[dict], min_zoom: float = 1.08, max_zoom: float = 1.4,
                  subject: tuple[float, float] = (0.5, 0.5), aspect: float = 16 / 9) -> list[float]:
    """Search region edges and center positions, largest feasible crop first."""
    base_width = min(1.0, (16 / 9) / aspect)
    base_height = min(1.0, aspect / (16 / 9))
    watermarks = [region["box"] for region in regions if region["kind"] == "channel_watermark"]
    text_boxes = [region["box"] for region in regions if region["kind"] in ("overlay_text", "burned_subtitles")]
    for avoid in (watermarks + text_boxes, watermarks):
        zooms = {min_zoom, max_zoom}
        for box in avoid:
            for space in (box[0], 1 - box[0] - box[2]):
                if space > 0:
                    zooms.add(base_width / space)
            for space in (box[1], 1 - box[1] - box[3]):
                if space > 0:
                    zooms.add(base_height / space)
        for zoom in sorted(value for value in zooms if min_zoom <= value <= max_zoom + 1e-8):
            width = base_width / zoom
            height = base_height / zoom
            horizontal = {0.0, 1 - width, max(0, min(1 - width, subject[0] - width / 2))}
            vertical = {0.0, 1 - height, max(0, min(1 - height, subject[1] - height / 2))}
            for box in avoid:
                horizontal.update((box[0] - width, box[0] + box[2]))
                vertical.update((box[1] - height, box[1] + box[3]))
            options = [[left, top, width, height] for left in horizontal for top in vertical
                       if -1e-8 <= left <= 1 - width + 1e-8 and -1e-8 <= top <= 1 - height + 1e-8
                       and not any(intersects([left, top, width, height], box) for box in avoid)]
            if options:
                return min(options, key=lambda box: (box[0] + width / 2 - subject[0]) ** 2 + (box[1] + height / 2 - subject[1]) ** 2)
    raise ProductionError("YouTube channel_watermark cannot be cropped within max_zoom")


def plan_transform(regions: list[dict], cue_id: str, config: YouTubeTransformConfig,
                   width: int = 1920, height: int = 1080) -> dict:
    """Map surviving regions into output coordinates before mirror/rotation."""
    if any(region["kind"] == "talking_head" for region in regions):
        raise ProductionError("YouTube talking_head is not eligible")
    crop = crop_avoiding(regions, config.min_zoom, config.max_zoom, aspect=width / height)
    blurred = []
    for region in regions:
        if not intersects(crop, region["box"]):
            continue
        if region["kind"] == "channel_watermark":
            raise ProductionError("YouTube channel_watermark remains")
        left, top, box_width, box_height = region["box"]
        right = min(crop[0] + crop[2], left + box_width)
        bottom = min(crop[1] + crop[3], top + box_height)
        left = max(left, crop[0])
        top = max(top, crop[1])
        blurred.append({"kind": region["kind"], "box": [(left - crop[0]) / crop[2], (top - crop[1]) / crop[3],
                                                         (right - left) / crop[2], (bottom - top) / crop[3]]})
    generator = random.Random(int.from_bytes(sha256(cue_id.encode()).digest()[:8], "big"))
    degrees = generator.uniform(1, config.rotate_degrees) * generator.choice((-1, 1))
    # Text in a blurred rectangle can remain partially readable; keep its orientation.
    mirrored = config.mirror and not any(region["kind"] in ("overlay_text", "burned_subtitles") for region in blurred)
    return {"crop": crop, "zoom": min(1 / crop[2], 1 / crop[3]), "rotate": degrees,
            "mirrored": mirrored, "blurred_regions": blurred,
            "transforms": ["crop", "scale", *(["boxblur"] if blurred else []),
                           *(["hflip"] if mirrored else []), "rotate", "rotation_zoom", "remove_audio"]}


def transform_filter(plan: dict, width: int = 1920, height: int = 1080) -> str:
    """Return a video-only complex graph with a named output."""
    left, top, crop_width, crop_height = plan["crop"]
    filters = [f"[0:v]crop=iw*{crop_width:.9f}:ih*{crop_height:.9f}:iw*{left:.9f}:ih*{top:.9f},scale={width}:{height},setsar=1[base]"]
    previous = "base"
    for index, region in enumerate(plan["blurred_regions"]):
        left, top, box_width, box_height = region["box"]
        pixel_left = max(0, math.floor(left * width) - 2)
        pixel_top = max(0, math.floor(top * height) - 2)
        pixel_width = min(width - pixel_left, math.ceil(box_width * width) + 4)
        pixel_height = min(height - pixel_top, math.ceil(box_height * height) + 4)
        radius = max(1, min(12, (min(pixel_width, pixel_height) - 1) // 2))
        filters.append(f"[{previous}]split=2[keep{index}][region{index}]")
        filters.append(f"[region{index}]crop={pixel_width}:{pixel_height}:{pixel_left}:{pixel_top},boxblur={radius}:2:chroma_radius=0[blur{index}]")
        filters.append(f"[keep{index}][blur{index}]overlay={pixel_left}:{pixel_top}[merged{index}]")
        previous = f"merged{index}"
    degrees = plan["rotate"]
    zoom = rotation_zoom(degrees)
    mirror = "hflip," if plan["mirrored"] else ""
    filters.append(f"[{previous}]{mirror}scale=ceil(iw*{zoom:.9f}/2)*2:ceil(ih*{zoom:.9f}/2)*2,rotate={degrees:.9f}*PI/180:ow=iw:oh=ih,crop={width}:{height},format=yuv420p[outv]")
    return ";\n".join(filters)


def transform_shot(shot: "Shot", output: Path, config: "ProductionConfig", width: int, height: int) -> None:
    """Render a silent transformed intermediate and retain audit metadata."""
    from .media import run_ffmpeg
    from .render import filter_script_arguments
    plan = plan_transform(shot.youtube["regions"], shot.cue_id, config.youtube_transform, width, height)
    graph = output.with_suffix(".ffgraph")
    graph.write_text(transform_filter(plan, config.width, config.height), encoding="utf-8")
    run_ffmpeg([config.ffmpeg, "-v", "error", "-y", "-i", shot.local_path,
                *filter_script_arguments(config.ffmpeg, graph), "-map", "[outv]", "-an",
                "-c:v", "libx264", "-preset", "fast", "-crf", "20", str(output)])
    for name in ("transforms", "zoom", "rotate", "mirrored", "blurred_regions"):
        setattr(shot, name, plan[name])
    shot.youtube["crop"] = plan["crop"]
    shot.local_path = str(output)
