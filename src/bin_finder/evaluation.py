from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DECISIONS = {"accepted", "rejected", "waitlist"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_project_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    return cleaned.strip("._") or "default"


def default_review_path(project_id: str) -> Path:
    base = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(base) / "BinFinder" / "reviews" if base else Path.cwd() / "reviews"
    return root / f"{_safe_project_id(project_id)}.json"


@dataclass(frozen=True)
class ReviewDecision:
    scene_id: str
    candidate_id: str
    decision: str
    provider: str = ""
    source_id: str = ""
    title: str = ""
    score: float = 0.0
    updated_at: str = ""
    source_url: str = ""
    creator: str = ""
    rights_status: str = "unknown"
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def normalized(self) -> "ReviewDecision":
        decision = self.decision.strip().lower()
        if decision not in _DECISIONS:
            raise ValueError(f"Unsupported review decision: {self.decision!r}")
        return ReviewDecision(
            scene_id=self.scene_id.strip(),
            candidate_id=self.candidate_id.strip(),
            decision=decision,
            provider=self.provider.strip(),
            source_id=self.source_id.strip(),
            title=self.title.strip(),
            score=max(0.0, min(1.0, float(self.score))),
            updated_at=self.updated_at or _now_iso(),
            source_url=self.source_url, creator=self.creator,
            rights_status=self.rights_status, source_metadata=dict(self.source_metadata),
        )


@dataclass(frozen=True)
class ABComparison:
    scene_id: str
    candidate_a_id: str
    candidate_b_id: str
    winner_id: str
    note: str = ""
    created_at: str = ""

    def normalized(self) -> "ABComparison":
        a = self.candidate_a_id.strip()
        b = self.candidate_b_id.strip()
        winner = self.winner_id.strip()
        if not a or not b or a == b:
            raise ValueError("A/B comparison requires two different candidate ids.")
        if winner not in {a, b}:
            raise ValueError("A/B winner must be candidate A or B.")
        return ABComparison(
            scene_id=self.scene_id.strip(),
            candidate_a_id=a,
            candidate_b_id=b,
            winner_id=winner,
            note=self.note.strip(),
            created_at=self.created_at or _now_iso(),
        )


@dataclass(frozen=True)
class EvaluationSummary:
    accepted: int
    rejected: int
    waitlist: int
    comparisons: int
    candidate_wins: dict[str, int]


class ReviewStore:
    FORMAT = "bin_finder_review_v1"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @classmethod
    def for_project(cls, project_id: str) -> "ReviewStore":
        return cls(default_review_path(project_id))

    def _load_payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "format": self.FORMAT,
                "decisions": [],
                "comparisons": [],
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "format": self.FORMAT,
                "decisions": [],
                "comparisons": [],
            }
        if not isinstance(payload, dict):
            return {
                "format": self.FORMAT,
                "decisions": [],
                "comparisons": [],
            }
        payload.setdefault("decisions", [])
        payload.setdefault("comparisons", [])
        payload["format"] = self.FORMAT
        return payload

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.path)

    def record_decision(self, decision: ReviewDecision) -> ReviewDecision:
        normalized = decision.normalized()
        payload = self._load_payload()
        keyed: dict[tuple[str, str], dict[str, Any]] = {}
        for item in payload.get("decisions", []):
            if not isinstance(item, dict):
                continue
            scene_id = str(item.get("scene_id") or "")
            candidate_id = str(item.get("candidate_id") or "")
            if scene_id and candidate_id:
                keyed[(scene_id, candidate_id)] = item
        keyed[(normalized.scene_id, normalized.candidate_id)] = asdict(normalized)
        payload["decisions"] = [
            keyed[key]
            for key in sorted(keyed)
        ]
        self._write_payload(payload)
        return normalized

    def add_comparison(self, comparison: ABComparison) -> ABComparison:
        normalized = comparison.normalized()
        payload = self._load_payload()
        comparisons = [
            item for item in payload.get("comparisons", []) if isinstance(item, dict)
        ]
        comparisons.append(asdict(normalized))
        payload["comparisons"] = comparisons
        self._write_payload(payload)
        return normalized

    def decisions(self) -> tuple[ReviewDecision, ...]:
        payload = self._load_payload()
        result: list[ReviewDecision] = []
        for item in payload.get("decisions", []):
            if not isinstance(item, dict):
                continue
            try:
                result.append(ReviewDecision(**item).normalized())
            except (TypeError, ValueError):
                continue
        return tuple(result)

    def comparisons(self) -> tuple[ABComparison, ...]:
        payload = self._load_payload()
        result: list[ABComparison] = []
        for item in payload.get("comparisons", []):
            if not isinstance(item, dict):
                continue
            try:
                result.append(ABComparison(**item).normalized())
            except (TypeError, ValueError):
                continue
        return tuple(result)

    def summary(self) -> EvaluationSummary:
        counts = {key: 0 for key in _DECISIONS}
        for decision in self.decisions():
            counts[decision.decision] += 1
        wins: dict[str, int] = {}
        comparisons = self.comparisons()
        for comparison in comparisons:
            wins[comparison.winner_id] = wins.get(comparison.winner_id, 0) + 1
        return EvaluationSummary(
            accepted=counts["accepted"],
            rejected=counts["rejected"],
            waitlist=counts["waitlist"],
            comparisons=len(comparisons),
            candidate_wins=wins,
        )
