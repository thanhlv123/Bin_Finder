from __future__ import annotations

from pathlib import Path

from bin_finder.local_index import LocalMediaIndex
from bin_finder.models import CandidateRecord
from bin_finder.providers.base import ProviderSearchResult, ProviderStatus, SearchRequest


class LocalLibraryProvider:
    key = "local"
    display_name = "Thư viện local"

    def __init__(
        self,
        root: str,
        *,
        index: LocalMediaIndex | None = None,
    ):
        self.root = Path(root).expanduser() if root.strip() else None
        self.index = (
            index
            if index is not None
            else LocalMediaIndex(self.root)
            if self.root is not None
            else None
        )

    def status(self) -> ProviderStatus:
        configured = bool(self.root and self.root.exists() and self.root.is_dir())
        return ProviderStatus(
            self.key,
            self.display_name,
            configured,
            "Sẵn sàng" if configured else "Chưa cấu hình thư mục local hợp lệ",
        )

    def _candidate(
        self,
        request: SearchRequest,
        score: float,
        record,
    ) -> CandidateRecord:
        digest = record.content_sha256[:16]
        return CandidateRecord(
            candidate_id=f"{request.scene_id}:local:{digest}",
            scene_id=request.scene_id,
            provider=self.key,
            source_id=f"local:{digest}",
            title=record.title,
            duration=0.0,
            score=round(max(0.0, min(1.0, score)), 6),
            rights_status="local_review_required",
            resolution="",
            source_url=record.path,
            preview_url=record.path,
            description=" ".join(
                part for part in (record.parent_text, record.transcript_text) if part
            )[:2000],
        )

    def search(self, request: SearchRequest) -> ProviderSearchResult:
        if (
            not self.root
            or not self.root.exists()
            or not self.root.is_dir()
            or self.index is None
        ):
            return ProviderSearchResult(
                self.key,
                notice="Thư viện local chưa cấu hình thư mục",
            )

        stats = self.index.sync()
        matches = self.index.search_text(request.query, limit=request.limit)
        candidates = [
            self._candidate(request, score, record)
            for score, record in matches
        ]
        notice = (
            f"Local index: {stats.indexed_records} file; "
            f"{stats.unchanged_files} unchanged; {stats.hashed_files} re-indexed."
        )
        return ProviderSearchResult(self.key, candidates, notice=notice)

    def search_by_image(
        self,
        *,
        scene_id: str,
        image_path: str | Path,
        limit: int = 20,
    ) -> ProviderSearchResult:
        if (
            not self.root
            or not self.root.exists()
            or not self.root.is_dir()
            or self.index is None
        ):
            return ProviderSearchResult(
                self.key,
                notice="Thư viện local chưa cấu hình thư mục",
            )

        self.index.sync()
        request = SearchRequest(
            scene_id=scene_id,
            query="",
            limit=limit,
        )
        matches = self.index.search_image(image_path, limit=limit)
        candidates = [
            self._candidate(request, score, record)
            for score, record in matches
        ]
        return ProviderSearchResult(
            self.key,
            candidates,
            notice="Search-by-image sử dụng perceptual frame hash local.",
        )
