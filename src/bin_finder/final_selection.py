"""F014 explicit final review. No Qt, downloads, extraction or implicit approval."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

from bin_finder.acquisition import verified_candidate_path
from bin_finder.acquisition.service import _provenance, _safe_text
from bin_finder.acceptance import evaluate_project
from bin_finder.integration_adapter import write_integration_package
from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.clips import ClipPolicy, ClipProposal, SmartClipPlanner
from bin_finder.diversity import DiversityCandidate, SourceDiversitySelector
from bin_finder.models import CandidateRecord, FootageProject, SceneRecord, SelectedClipRecord
from bin_finder.verification import HeuristicContextVerifier, VerificationReranker
from bin_finder.workflow import WorkflowItemResult


class FinalSelectionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FinalReviewOption:
    clip_id: str
    scene: SceneRecord
    candidate: CandidateRecord
    local_file: str
    proposal: ClipProposal
    semantic_score: float
    vlm_score: float
    final_score: float
    media_sha256: str
    verification_provider: str

    @property
    def unit_id(self):
        return self.proposal.unit_id


@dataclass(frozen=True)
class ApprovalResult:
    accepted: bool
    reason: str
    selections: tuple[SelectedClipRecord, ...]


def build_final_project(project_id, scenes, selections, output_dir) -> FootageProject:
    """Build only from final records; preliminary candidate cards are invalid."""
    scenes = sorted(scenes, key=lambda s: (s.order, s.scene_id))
    scene_map = {s.scene_id: s for s in scenes}
    clips = {}
    for clip in selections:
        if not isinstance(clip, SelectedClipRecord):
            raise TypeError("Final SelectedClipRecord required")
        if clip.scene_id not in scene_map or clip.scene_order != scene_map[clip.scene_id].order:
            raise FinalSelectionError("unknown-scene")
        if clip.scene_id in clips:
            raise FinalSelectionError("duplicate-scene")
        clips[clip.scene_id] = clip
    return FootageProject(project_id, Path(output_dir), list(scenes),
                          [clips[s.scene_id] for s in scenes if s.scene_id in clips])


def _score(value):
    if value is None or not math.isfinite(value) or not 0 <= value <= 1:
        raise FinalSelectionError("missing-score-evidence")
    return float(value)


class FinalSelectionService:
    def __init__(self, selector=None):
        self.selector = selector or SourceDiversitySelector()

    def _media(self, scene, item):
        candidate, analysis = item.candidate, item.analysis
        if scene.scene_id != candidate.scene_id or item.stage != "analyzed" or analysis is None:
            raise FinalSelectionError("analysis-required")
        if item.local_path is None:
            raise FinalSelectionError("local-media-required")
        path = Path(item.local_path)
        if path.is_symlink() or not path.is_file():
            raise FinalSelectionError("local-media-required")
        path = path.resolve()
        if candidate.provider == "local":
            expected = Path(candidate.preview_url or candidate.source_url).expanduser().resolve()
        else:
            expected = verified_candidate_path(candidate)
        if expected != path or Path(analysis.source_path).resolve() != path:
            raise FinalSelectionError("media-path-mismatch")
        if fingerprint_file(path).sha256 != analysis.fingerprint.sha256:
            raise FinalSelectionError("media-identity-mismatch")
        if (not math.isfinite(analysis.metadata.duration) or analysis.metadata.duration <= 0
                or analysis.metadata.width <= 0 or analysis.metadata.height <= 0):
            raise FinalSelectionError("invalid-media-metadata")
        if not candidate.source_id or not candidate.provider:
            raise FinalSelectionError("missing-source-identity")
        return path

    def prepare(self, scene: SceneRecord, item: WorkflowItemResult) -> WorkflowItemResult:
        """Explicit F014 step; never changes F013 defaults or repairs rejected evidence."""
        self._media(scene, item)
        verified, proposals = item.verified, item.proposals
        if not verified and not proposals and item.downstream.get("verification") == "not_configured":
            verified = tuple(VerificationReranker(HeuristicContextVerifier()).rerank(scene, list(item.ranked)))
        if not proposals and item.downstream.get("clip_planning") in {"awaiting_verification", "not_configured"}:
            proposals = tuple(SmartClipPlanner().propose_many([
                v for v in verified if v.status == "verified" and v.verification is not None]))
        return replace(item, verified=verified, proposals=proposals,
                       downstream={**item.downstream, "final_review": "prepared"})

    def options(self, scene, item) -> tuple[FinalReviewOption, ...]:
        path = self._media(scene, item)
        policy = ClipPolicy()
        options = []
        for proposal in item.proposals:
            ranked = [r for r in item.ranked if r.unit.unit_id == proposal.unit_id]
            verified = [v for v in item.verified if v.segment.unit.unit_id == proposal.unit_id]
            if len(ranked) != 1 or len(verified) != 1:
                continue
            rank, verification = ranked[0], verified[0]
            unit = rank.unit
            if (not proposal.accepted or verification.status != "verified"
                    or verification.verification is None
                    or verification.verification.unit_id != unit.unit_id
                    or verification.segment != rank):
                continue
            if (Path(proposal.source_path).resolve() != path
                    or Path(unit.source_path).resolve() != path):
                continue
            times = (proposal.start, proposal.end, unit.start, unit.end)
            if (not all(math.isfinite(t) for t in times)
                    or not 0 <= unit.start <= proposal.start < proposal.end <= unit.end
                    or unit.end > item.analysis.metadata.duration
                    or not policy.min_duration <= proposal.duration <= policy.max_duration):
                continue
            try:
                semantic = _score(rank.scores.final)
                vlm = _score(verification.verification_score)
                final = _score(verification.final_score)
            except FinalSelectionError:
                continue
            c = item.candidate
            identity = [scene.scene_id, c.candidate_id, c.provider, c.source_id,
                        item.analysis.fingerprint.sha256, unit.unit_id,
                        float(proposal.start), float(proposal.end)]
            clip_id = "clip_" + hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
            options.append(FinalReviewOption(clip_id, scene, c, str(path), proposal,
                semantic, vlm, final, item.analysis.fingerprint.sha256, verification.verification.provider))
        return tuple(sorted(options, key=lambda o: (-o.final_score, o.clip_id)))

    def approve(self, scene, item, clip_id, scenes, selections=(), *, human_approved=False):
        previous = tuple(selections)
        if human_approved is not True:
            return ApprovalResult(False, "explicit-approval-required", previous)
        try:
            options = self.options(scene, item)
            option = next((o for o in options if o.clip_id == clip_id), None)
            if option is None:
                return ApprovalResult(False, "invalid-final-option", previous)
            best = max(o.final_score for o in options)
            if option.final_score < max(self.selector.policy.min_score,
                                             best - self.selector.policy.max_score_drop):
                return ApprovalResult(False, "quality-drop-guardrail", previous)
            c, proposal = option.candidate, option.proposal
            provenance = _provenance(c)  # Reuse F012's allowlist and signed-URL/secret filtering.
            clip = SelectedClipRecord(option.clip_id, scene.scene_id, scene.order, c.provider, c.source_id,
                _safe_text(c.title), option.local_file, proposal.start, proposal.end, proposal.duration,
                option.semantic_score, option.vlm_score, option.final_score,
                provenance["rights_status"], provenance["source_url"], provenance["creator"],
                {**provenance["source_metadata"], "media_sha256": option.media_sha256,
                 "duplicate_group": _safe_text(c.source_metadata.get("duplicate_group", "")),
                 "proposal_unit_id": option.unit_id, "verification_provider": option.verification_provider})
            proposed = tuple(c for c in previous if c.scene_id != scene.scene_id) + (clip,)
            project = build_final_project("review", scenes, proposed, ".")
            candidates = [DiversityCandidate(c.clip_id, c.scene_id, c.scene_order, c.source_id,
                c.start, c.end, c.final_score, c.provider, str(c.source_metadata.get("duplicate_group", "")))
                for c in project.selected_clips]
            result = self.selector.select(candidates)
            conflict = next((d for d in result.decisions if d.candidate is None), None)
            if conflict:
                return ApprovalResult(False, conflict.conflict_reasons[0]
                                      if conflict.conflict_reasons else conflict.reason, previous)
            # One offered option per scene: F008 cannot substitute any prior human choice.
            return ApprovalResult(True, "approved", tuple(project.selected_clips))
        except (FinalSelectionError, OSError, ValueError) as error:
            return ApprovalResult(False, error.code if isinstance(error, FinalSelectionError)
                                  else "media-unavailable", previous)


def handoff_final_project(project_id, scenes, selections, output_dir):
    """Explicit F010 handoff; no incomplete override and no output inside the repository."""
    root = Path(output_dir).expanduser().resolve()
    source_root = Path(__file__).resolve().parents[2]
    if root == source_root or source_root in root.parents:
        raise FinalSelectionError("output-inside-source-tree")
    project = build_final_project(project_id, scenes, selections, root)
    return write_integration_package(root, project, evaluate_project(project))
