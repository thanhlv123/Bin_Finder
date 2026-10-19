from __future__ import annotations

import hashlib
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.analysis.transcript import load_transcript_sidecar
from bin_finder.retrieval.lexical import BM25Ranker
from bin_finder.visual_hash import FrameHashExtractor, hamming_similarity


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}


def default_local_index_path(root: Path) -> Path:
    digest = hashlib.sha256(str(root.resolve()).casefold().encode("utf-8")).hexdigest()[:20]
    base = os.environ.get("LOCALAPPDATA", "").strip()
    parent = Path(base) / "BinFinder" / "indexes" if base else Path.cwd() / "indexes"
    return parent / f"local_{digest}.sqlite3"


@dataclass(frozen=True)
class LocalIndexRecord:
    content_sha256: str
    path: str
    size_bytes: int
    mtime_ns: int
    title: str
    parent_text: str
    transcript_text: str
    visual_hash: str = ""

    @property
    def searchable_text(self) -> str:
        return " ".join(
            part.strip()
            for part in (self.title, self.parent_text, self.transcript_text)
            if part and part.strip()
        ).strip()


@dataclass(frozen=True)
class LocalSyncStats:
    scanned_files: int
    unchanged_files: int
    hashed_files: int
    removed_records: int
    indexed_records: int


class LocalMediaIndex:
    def __init__(
        self,
        root: str | Path,
        *,
        db_path: str | Path | None = None,
        frame_hasher: FrameHashExtractor | None = None,
    ):
        self.root = Path(root).expanduser().resolve()
        self.db_path = Path(db_path) if db_path is not None else default_local_index_path(self.root)
        self.frame_hasher = frame_hasher or FrameHashExtractor()

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=15.0)
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS media (
                content_sha256 TEXT PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                size_bytes INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                title TEXT NOT NULL,
                parent_text TEXT NOT NULL,
                transcript_text TEXT NOT NULL,
                visual_hash TEXT NOT NULL DEFAULT '',
                indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_media_path ON media(path)"
        )
        connection.commit()
        return connection

    def _iter_media(self) -> Iterable[Path]:
        if not self.root.exists() or not self.root.is_dir():
            return ()
        return (
            path
            for path in self.root.rglob("*")
            if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS
        )

    @staticmethod
    def _transcript_text(path: Path) -> str:
        try:
            _, _, segments = load_transcript_sidecar(path)
        except OSError:
            return ""
        return " ".join(segment.text.strip() for segment in segments if segment.text.strip())

    def sync(self) -> LocalSyncStats:
        scanned = unchanged = hashed = 0
        live_paths: set[str] = set()

        with self._connect() as connection:
            existing_by_path = {
                str(row["path"]): row
                for row in connection.execute(
                    "SELECT content_sha256, path, size_bytes, mtime_ns FROM media"
                )
            }

            for path in self._iter_media():
                scanned += 1
                resolved = str(path.resolve())
                live_paths.add(resolved)
                stat = path.stat()
                existing = existing_by_path.get(resolved)
                if (
                    existing is not None
                    and int(existing["size_bytes"]) == stat.st_size
                    and int(existing["mtime_ns"]) == stat.st_mtime_ns
                ):
                    unchanged += 1
                    continue

                fingerprint = fingerprint_file(path)
                hashed += 1
                transcript_text = self._transcript_text(path)
                parent_text = " ".join(path.parts[-3:-1])

                duplicate = connection.execute(
                    "SELECT visual_hash FROM media WHERE content_sha256 = ?",
                    (fingerprint.sha256,),
                ).fetchone()
                visual_hash = str(duplicate["visual_hash"]) if duplicate is not None else ""

                connection.execute(
                    "DELETE FROM media WHERE path = ? AND content_sha256 <> ?",
                    (resolved, fingerprint.sha256),
                )
                connection.execute(
                    """
                    INSERT INTO media(
                        content_sha256, path, size_bytes, mtime_ns,
                        title, parent_text, transcript_text, visual_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(content_sha256) DO UPDATE SET
                        path = excluded.path,
                        size_bytes = excluded.size_bytes,
                        mtime_ns = excluded.mtime_ns,
                        title = excluded.title,
                        parent_text = excluded.parent_text,
                        transcript_text = excluded.transcript_text,
                        visual_hash = CASE
                            WHEN media.visual_hash <> '' THEN media.visual_hash
                            ELSE excluded.visual_hash
                        END,
                        indexed_at = CURRENT_TIMESTAMP
                    """,
                    (
                        fingerprint.sha256,
                        resolved,
                        fingerprint.size_bytes,
                        fingerprint.mtime_ns,
                        path.stem,
                        parent_text,
                        transcript_text,
                        visual_hash,
                    ),
                )

            rows = list(connection.execute("SELECT content_sha256, path FROM media"))
            removed = 0
            for row in rows:
                indexed_path = str(row["path"])
                if indexed_path not in live_paths:
                    connection.execute(
                        "DELETE FROM media WHERE content_sha256 = ?",
                        (str(row["content_sha256"]),),
                    )
                    removed += 1

            connection.commit()
            indexed_records = int(
                connection.execute("SELECT COUNT(*) FROM media").fetchone()[0]
            )

        return LocalSyncStats(
            scanned_files=scanned,
            unchanged_files=unchanged,
            hashed_files=hashed,
            removed_records=removed,
            indexed_records=indexed_records,
        )

    def records(self) -> list[LocalIndexRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT content_sha256, path, size_bytes, mtime_ns,
                       title, parent_text, transcript_text, visual_hash
                FROM media
                ORDER BY path COLLATE NOCASE
                """
            ).fetchall()
        return [
            LocalIndexRecord(
                content_sha256=str(row["content_sha256"]),
                path=str(row["path"]),
                size_bytes=int(row["size_bytes"]),
                mtime_ns=int(row["mtime_ns"]),
                title=str(row["title"]),
                parent_text=str(row["parent_text"]),
                transcript_text=str(row["transcript_text"]),
                visual_hash=str(row["visual_hash"]),
            )
            for row in rows
        ]

    def search_text(self, query: str, *, limit: int = 20) -> list[tuple[float, LocalIndexRecord]]:
        records = self.records()
        if not records:
            return []
        documents = [record.searchable_text for record in records]
        scores = BM25Ranker(documents).normalized_scores(query)
        ranked = [
            (score, record)
            for score, record in zip(scores, records)
            if score > 0 or not query.strip()
        ]
        ranked.sort(key=lambda pair: (-pair[0], pair[1].title.casefold(), pair[1].path.casefold()))
        return ranked[: max(0, limit)]

    def _ensure_visual_hash(self, record: LocalIndexRecord) -> LocalIndexRecord:
        if record.visual_hash:
            return record
        visual_hash = self.frame_hasher.hash_media(record.path)
        if not visual_hash:
            return record
        with self._connect() as connection:
            connection.execute(
                "UPDATE media SET visual_hash = ? WHERE content_sha256 = ?",
                (visual_hash, record.content_sha256),
            )
            connection.commit()
        return LocalIndexRecord(
            content_sha256=record.content_sha256,
            path=record.path,
            size_bytes=record.size_bytes,
            mtime_ns=record.mtime_ns,
            title=record.title,
            parent_text=record.parent_text,
            transcript_text=record.transcript_text,
            visual_hash=visual_hash,
        )

    def search_image(
        self,
        image_path: str | Path,
        *,
        limit: int = 20,
    ) -> list[tuple[float, LocalIndexRecord]]:
        query_hash = self.frame_hasher.hash_media(image_path)
        if not query_hash:
            return []
        ranked: list[tuple[float, LocalIndexRecord]] = []
        for record in self.records():
            enriched = self._ensure_visual_hash(record)
            if not enriched.visual_hash:
                continue
            score = hamming_similarity(query_hash, enriched.visual_hash)
            ranked.append((score, enriched))
        ranked.sort(key=lambda pair: (-pair[0], pair[1].title.casefold(), pair[1].path.casefold()))
        return ranked[: max(0, limit)]
