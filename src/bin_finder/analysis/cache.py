from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from bin_finder.analysis.models import CandidateAnalysis


def default_analysis_cache_path() -> Path:
    base = os.environ.get("LOCALAPPDATA", "").strip()
    if base:
        root = Path(base) / "BinFinder" / "cache"
    else:
        root = Path.cwd() / "cache"
    return root / "analysis.sqlite3"


class AnalysisCache:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else default_analysis_cache_path()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.path, timeout=10.0)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        # SQLite's transaction context commits/rolls back but does not close.
        # Own the handle before schema setup so initialization failures close it too.
        with closing(self._connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS analysis_cache (
                        cache_key TEXT PRIMARY KEY,
                        sha256 TEXT NOT NULL,
                        transcript_sha256 TEXT NOT NULL,
                        analyzer_version TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_analysis_identity "
                    "ON analysis_cache(sha256, transcript_sha256, analyzer_version)"
                )
                yield connection

    def get(
        self,
        sha256: str,
        transcript_sha256: str,
        analyzer_version: str,
    ) -> CandidateAnalysis | None:
        transcript_identity = transcript_sha256 or "none"
        cache_key = f"{sha256}:{transcript_identity}:{analyzer_version}"
        with self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM analysis_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
            if not isinstance(payload, dict):
                return None
            return CandidateAnalysis.from_dict(payload)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def put(self, analysis: CandidateAnalysis) -> None:
        payload = json.dumps(
            analysis.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO analysis_cache(
                    cache_key,
                    sha256,
                    transcript_sha256,
                    analyzer_version,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = CURRENT_TIMESTAMP
                """,
                (
                    analysis.cache_key,
                    analysis.fingerprint.sha256,
                    analysis.transcript_sha256 or "",
                    analysis.analyzer_version,
                    payload,
                ),
            )

    def clear(self) -> None:
        if not self.path.exists():
            return
        with self._connection() as connection:
            connection.execute("DELETE FROM analysis_cache")
