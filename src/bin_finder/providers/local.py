from __future__ import annotations

import hashlib
import re
from pathlib import Path

from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus, SearchRequest


_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _tokens(value: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(value) if len(token) > 1}


class LocalLibraryProvider:
    key = "local"
    display_name = "Thư viện local"

    def __init__(self, root: str):
        self.root = Path(root).expanduser() if root.strip() else None

    def status(self) -> ProviderStatus:
        configured = bool(self.root and self.root.exists() and self.root.is_dir())
        return ProviderStatus(
            self.key,
            self.display_name,
            configured,
            "Sẵn sàng" if configured else "Chưa cấu hình thư mục local hợp lệ",
        )

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        if not self.root or not self.root.exists() or not self.root.is_dir():
            return ProviderSearchResult(self.key, notice="Thư viện local chưa cấu hình thư mục")
        query_tokens = _tokens(request.query)
        ranked: list[tuple[float, Path]] = []
        for path in self.root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _VIDEO_EXTENSIONS:
                continue
            searchable = " ".join((path.stem, *path.parts[-3:-1]))
            haystack = _tokens(searchable)
            overlap = len(query_tokens & haystack)
            if query_tokens and overlap == 0:
                continue
            score = overlap / max(1, len(query_tokens))
            ranked.append((score, path))
        ranked.sort(key=lambda pair: (-pair[0], pair[1].name.lower()))

        candidates: list[CandidateRecord] = []
        for score, path in ranked[: request.limit]:
            digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:16]
            candidates.append(
                CandidateRecord(
                    candidate_id=f"{request.scene_id}:local:{digest}",
                    scene_id=request.scene_id,
                    provider=self.key,
                    source_id=f"local:{digest}",
                    title=path.stem,
                    duration=0.0,
                    score=score,
                    rights_status="local_review_required",
                    resolution="",
                    source_url=str(path),
                    preview_url=str(path),
                    description=str(path.parent),
                )
            )
        return ProviderSearchResult(self.key, candidates)
