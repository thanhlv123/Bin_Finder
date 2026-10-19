from __future__ import annotations

from typing import Mapping, Sequence

from bin_finder.clips.models import ClipPolicy, ClipProposal
from bin_finder.verification.models import VerifiedSegment


def _round_time(value: float) -> float:
    return round(max(0.0, float(value)), 3)


class SmartClipPlanner:
    def __init__(self, policy: ClipPolicy | None = None):
        self.policy = policy or ClipPolicy()
        self.policy.validate()

    def propose(
        self,
        segment: VerifiedSegment,
        *,
        anchor_time: float | None = None,
    ) -> ClipProposal:
        unit = segment.segment.unit
        shot_start = float(unit.start)
        shot_end = float(unit.end)
        shot_duration = max(0.0, shot_end - shot_start)
        score = max(0.0, min(1.0, float(segment.final_score)))

        if shot_duration <= 0:
            return ClipProposal(
                unit_id=unit.unit_id,
                source_path=unit.source_path,
                start=_round_time(shot_start),
                end=_round_time(shot_start),
                score=score,
                accepted=False,
                reason="invalid-shot",
                anchor_time=anchor_time,
            )

        if shot_duration < self.policy.min_duration:
            return ClipProposal(
                unit_id=unit.unit_id,
                source_path=unit.source_path,
                start=_round_time(shot_start),
                end=_round_time(shot_end),
                score=score,
                accepted=self.policy.allow_short_shots,
                reason=(
                    "short-shot-allowed"
                    if self.policy.allow_short_shots
                    else "shot-too-short"
                ),
                anchor_time=anchor_time,
            )

        if shot_duration <= self.policy.max_duration:
            return ClipProposal(
                unit_id=unit.unit_id,
                source_path=unit.source_path,
                start=_round_time(shot_start),
                end=_round_time(shot_end),
                score=score,
                accepted=True,
                reason="whole-shot",
                anchor_time=anchor_time,
            )

        target = self.policy.target_duration
        anchor = (
            float(anchor_time)
            if anchor_time is not None
            else shot_start + shot_duration / 2.0
        )
        anchor = max(shot_start, min(shot_end, anchor))
        start = anchor - target / 2.0
        start = max(shot_start, min(start, shot_end - target))
        end = start + target

        return ClipProposal(
            unit_id=unit.unit_id,
            source_path=unit.source_path,
            start=_round_time(start),
            end=_round_time(end),
            score=score,
            accepted=True,
            reason="target-window",
            anchor_time=_round_time(anchor),
        )

    def propose_many(
        self,
        segments: Sequence[VerifiedSegment],
        *,
        anchors: Mapping[str, float] | None = None,
        limit: int | None = None,
        include_rejected: bool = False,
    ) -> list[ClipProposal]:
        anchors = anchors or {}
        proposals = [
            self.propose(
                segment,
                anchor_time=anchors.get(segment.segment.unit.unit_id),
            )
            for segment in segments
        ]
        if not include_rejected:
            proposals = [proposal for proposal in proposals if proposal.accepted]
        if limit is not None:
            proposals = proposals[: max(0, int(limit))]
        return proposals
