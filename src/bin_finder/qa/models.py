"""Serializable QA findings and reports."""
from dataclasses import asdict, dataclass, field
from typing import Literal


@dataclass
class Finding:
    code: str
    severity: Literal["blocker", "warning", "info"]
    message: str
    cue_id: str | None = None
    start: float | None = None
    end: float | None = None
    details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in ("blocker", "warning", "info"):
            raise ValueError("Invalid severity")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "Finding":
        return cls(**payload)


@dataclass
class QaReport:
    video_path: str
    production_path: str
    checked_at: str
    findings: list[Finding] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    passed: bool = True

    def __post_init__(self) -> None:
        self.passed = not any(item.severity == "blocker" for item in self.findings)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["passed"] = not any(item.severity == "blocker" for item in self.findings)
        return payload

    @classmethod
    def from_dict(cls, payload: dict) -> "QaReport":
        values = dict(payload)
        values["findings"] = [Finding.from_dict(item) for item in values["findings"]]
        return cls(**values)


def sorted_findings(findings: list[Finding]) -> list[Finding]:
    """Order by severity, then timeline position, preserving ties."""
    levels = {"blocker": 0, "warning": 1, "info": 2}
    return sorted(findings, key=lambda item: (levels[item.severity], item.start if item.start is not None else -1))


def summarize_findings(findings: list[Finding]) -> list[str]:
    """Collapse frequent codes before limiting terminal output."""
    ordered = sorted_findings(findings)
    groups: dict[tuple[str, str], list[Finding]] = {}
    for finding in ordered:
        groups.setdefault((finding.code, finding.severity), []).append(finding)
    lines: list[str] = []
    emitted: set[tuple[str, str]] = set()
    for finding in ordered:
        key = (finding.code, finding.severity)
        group = groups[key]
        if len(group) > 3:
            if key in emitted:
                continue
            emitted.add(key)
            cue_ids = list(dict.fromkeys(item.cue_id for item in group if item.cue_id))
            references = ", ".join(cue_ids[:3])
            if len(cue_ids) > 3:
                references += ", …"
            lines.append(f"[{finding.severity}] {finding.code} ×{len(group)}: {references or finding.message}")
        else:
            lines.append(f"[{finding.severity}] {finding.code}: {finding.message}")
    return lines
