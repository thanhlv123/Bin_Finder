"""BF-S03B research: explicit local-media gate BEFORE any vision inference.

No network, FFmpeg, Ollama, provider APIs, downloads, video reading or
filesystem writes. Only read-only local path validation and candidate mapping.
A metadata score is never treated as visual proof or approval.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path

from bin_finder.search.slot_metadata_rank import MetadataRankResult


class LocalVisionGateError(ValueError):
    """Fixed errors only; do not disclose absolute user paths or API URLs."""


_ALLOWED_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".webm"})


@dataclass(frozen=True)
class LocalMediaForReview:
    """The user supplies a real local file; never download from source_url."""
    provider: str
    source_id: str
    local_file: str = field(repr=False)
    start: float = 0.0
    end: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        return (self.provider, self.source_id)


@dataclass(frozen=True)
class LocalVisionPolicy:
    """Limits are per explicit human-started research attempt."""
    max_candidates: int = 5
    max_clip_seconds: float = 120.0
    max_file_bytes: int = 4_000_000_000

    def validate(self) -> None:
        if (type(self.max_candidates) is not int or not 1 <= self.max_candidates <= 5
                or type(self.max_clip_seconds) not in (int, float)
                or not math.isfinite(self.max_clip_seconds)
                or not 1 <= self.max_clip_seconds <= 600
                or type(self.max_file_bytes) is not int
                or not 1_000_000 <= self.max_file_bytes <= 20_000_000_000):
            raise LocalVisionGateError("invalid-local-vision-policy")


@dataclass(frozen=True)
class PreparedVisionUnit:
    """A bounded *proposed* local sample, not verified footage."""
    slot_id: str
    provider: str
    source_id: str
    source_file: Path = field(repr=False)
    start: float = 0.0
    end: float = 0.0
    status: str = "local-sample-ready-not-verified"

    @property
    def key(self) -> tuple[str, str]:
        return (self.provider, self.source_id)


@dataclass(frozen=True)
class LocalVisionGateResult:
    slot_id: str
    status: str
    prepared: tuple[PreparedVisionUnit, ...] = ()
    not_prepared_count: int = 0
    model_calls: int = 0
    provider_calls: int = 0


def _unsafe_ancestor(path: Path) -> bool:
    try:
        return any(
            p.is_symlink() or getattr(p, "is_junction", lambda: False)()
            for p in (path, *path.parents)
        )
    except OSError:
        return True


def prepare_local_vision(
    ranking: MetadataRankResult,
    media: tuple[LocalMediaForReview, ...],
    *,
    allowed_root: Path,
    approve_local_inspection: bool = False,
    policy: LocalVisionPolicy | None = None,
) -> LocalVisionGateResult:
    """Validate user-owned local clips without sampling, network or model.

    Does not infer file location from URLs or source IDs. Every media item
    must match a BF-S03A ranked candidate. Never chooses items automatically.
    """
    if not isinstance(ranking, MetadataRankResult) or not isinstance(media, tuple):
        raise LocalVisionGateError("invalid-local-vision-input")
    constraints = policy or LocalVisionPolicy()
    constraints.validate()
    if (any(not isinstance(item, LocalMediaForReview) for item in media)
            or len(media) > constraints.max_candidates
            or len({item.key for item in media}) != len(media)):
        raise LocalVisionGateError("invalid-local-media-list")
    if type(approve_local_inspection) is not bool:
        raise LocalVisionGateError("invalid-approval-flag")
    if not approve_local_inspection:
        return LocalVisionGateResult(ranking.slot_id, "manual-opt-in-required",
                                     not_prepared_count=len(media))
    if not media:
        return LocalVisionGateResult(ranking.slot_id, "no-manual-media-selected")

    known = {item.key for item in ranking.ranked}
    if any(item.key not in known for item in media):
        raise LocalVisionGateError("unranked-candidate-rejected")

    if not isinstance(allowed_root, Path):
        raise LocalVisionGateError("invalid-media-root")
    try:
        if _unsafe_ancestor(allowed_root) or not allowed_root.is_dir():
            raise LocalVisionGateError("unsafe-media-root")
        root = allowed_root.resolve(strict=True)
    except OSError:
        raise LocalVisionGateError("unsafe-media-root") from None

    prepared: list[PreparedVisionUnit] = []
    rejected = 0
    for item in media:
        if (not isinstance(item.local_file, str) or not item.local_file.strip()
                or "://" in item.local_file or "\x00" in item.local_file):
            rejected += 1
            continue
        path = Path(item.local_file)
        if (not path.is_absolute() or path.suffix.casefold() not in _ALLOWED_EXTENSIONS
                or _unsafe_ancestor(path)):
            rejected += 1
            continue
        if (type(item.start) not in (int, float)
                or type(item.end) not in (int, float)
                or not math.isfinite(item.start) or not math.isfinite(item.end)
                or item.start < 0 or item.end <= item.start
                or item.end - item.start > constraints.max_clip_seconds):
            rejected += 1
            continue
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or not resolved.is_file():
                rejected += 1
                continue
            size = resolved.stat().st_size
            if size <= 0 or size > constraints.max_file_bytes:
                rejected += 1
                continue
        except OSError:
            rejected += 1
            continue
        prepared.append(PreparedVisionUnit(
            slot_id=ranking.slot_id, provider=item.provider,
            source_id=item.source_id, source_file=resolved,
            start=float(item.start), end=float(item.end),
        ))
    return LocalVisionGateResult(
        slot_id=ranking.slot_id,
        status=("local-ready-for-inference-approval" if prepared
                else "no-safe-local-media"),
        prepared=tuple(prepared), not_prepared_count=rejected,
    )
