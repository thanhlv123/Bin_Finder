from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from bin_finder.acquisition import (
    AcquisitionCancelled, AcquisitionRequest, AcquisitionService, verified_candidate_path,
)
from bin_finder.analysis.cache import AnalysisCache
from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.analysis.models import CandidateAnalysis
from bin_finder.analysis.service import CandidateAnalysisService
from bin_finder.evaluation import ReviewDecision
from bin_finder.models import CandidateRecord, SceneRecord
from bin_finder.retrieval.engine import HybridRetrievalEngine
from bin_finder.retrieval.models import RankedSegment
from bin_finder.clips.models import ClipProposal
from bin_finder.verification.models import VerifiedSegment
from .state import RunState, STAGES, WorkflowStateError, digest, now, safe_text


def default_work_root(project_id: str) -> Path:
    base = os.environ.get("LOCALAPPDATA", "").strip()
    root = Path(base) / "BinFinder" if base else Path.home() / ".bin_finder"
    return root / "workflows" / digest(project_id)[:24]


@dataclass(frozen=True)
class WorkflowRequest:
    scenes: tuple[SceneRecord, ...]
    candidates: tuple[CandidateRecord, ...]
    reviews: tuple[ReviewDecision, ...] = ()
    authorize_acquisition: bool = False


@dataclass(frozen=True)
class WorkflowProgress:
    item_index: int
    item_count: int
    scene_id: str
    candidate_id: str
    stage: str
    percent: int | None = None


@dataclass
class WorkflowItemResult:
    candidate: CandidateRecord
    stage: str = "pending"
    code: str = ""
    message: str = ""
    local_path: Path | None = None
    analysis: CandidateAnalysis | None = None
    acquisition_reused: bool = False
    ranked: tuple[RankedSegment, ...] = ()
    verified: tuple[VerifiedSegment, ...] = ()
    proposals: tuple[ClipProposal, ...] = ()
    downstream: dict[str, str] = field(default_factory=lambda: {
        "retrieval": "pending", "verification": "not_configured",
        "clip_planning": "awaiting_verification", "extraction": "not_requested",
        "local_index": "not_configured", "diversity": "awaiting_final_selection",
        "final_review": "required", "readiness": "not_evaluated", "handoff": "not_requested",
    })


@dataclass(frozen=True)
class WorkflowResult:
    items: tuple[WorkflowItemResult, ...]
    state_path: Path

    @property
    def cancelled(self):
        return any(item.stage == "cancelled" for item in self.items)

    @property
    def by_scene(self):
        return {scene_id: tuple(item for item in self.items if item.candidate.scene_id == scene_id)
                for scene_id in dict.fromkeys(item.candidate.scene_id for item in self.items)}


class ItemFailure(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class WorkflowService:
    """Single writer per work directory. Callers supply current F009 review state.

    F003 has no interruption API: cancellation is checked before and after it,
    and its current bounded subprocess call is allowed to finish safely.
    """
    def __init__(self, work_dir=None, *, project_id="default", acquisition=None,
                 analysis=None, retrieval=None, verifier=None, planner=None):
        self.root = Path(work_dir) if work_dir is not None else default_work_root(project_id)
        self.acquisition = acquisition if acquisition is not None else AcquisitionService()
        self.analysis = analysis if analysis is not None else CandidateAnalysisService(
            cache=AnalysisCache(self.root / "analysis.sqlite3"))
        self.retrieval = retrieval if retrieval is not None else HybridRetrievalEngine()
        self.verifier, self.planner = verifier, planner

    def run(self, request: WorkflowRequest, *, progress=lambda event: None,
            cancelled=lambda: False) -> WorkflowResult:
        lock = self.root / "workflow.lock"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            handle = lock.open("x")
        except Exception:
            raise WorkflowStateError("Workflow directory unavailable or already in use.") from None
        try:
            return self._run(request, progress, cancelled)
        finally:
            handle.close()
            try:
                lock.unlink(missing_ok=True)
            except OSError:
                pass  # Retain results; the abandoned lock blocks unsafe concurrent reuse.

    def _run(self, request, progress, cancelled):
        store = RunState(self.root)
        store.load()
        store.write()  # Fail at initialization if the run cannot be persisted.
        scenes = {scene.scene_id: scene for scene in request.scenes}
        ordered = sorted(request.candidates, key=lambda c: (
            scenes[c.scene_id].order if c.scene_id in scenes else float("inf"),
            c.scene_id, c.candidate_id, c.provider, c.source_id))
        results = []
        stopping = False
        for index, original in enumerate(ordered, 1):
            item = WorkflowItemResult(original)
            results.append(item)
            identity = [original.scene_id, original.candidate_id, original.provider, original.source_id]
            key = digest(identity)
            signature = digest([identity, original.preview_url, original.source_url])
            previous = store.items.get(key)
            record = {"scene_id": safe_text(original.scene_id),
                      "candidate_id": safe_text(original.candidate_id),
                      "provider": safe_text(original.provider), "source_id": safe_text(original.source_id),
                      "signature": signature, "stage": "pending", "updated_at": now()}

            def emit(stage, percent=None):
                # An observer cannot turn completed work into a failed item.
                try:
                    progress(WorkflowProgress(index, len(ordered), original.scene_id,
                                              original.candidate_id, stage, percent))
                except Exception:
                    pass

            def save(stage):
                item.stage = record["stage"] = stage
                record["updated_at"] = now()
                store.items[key] = dict(record)
                store.write()
                emit(stage)

            def check_cancel():
                if cancelled():
                    raise AcquisitionCancelled()

            try:
                if stopping or cancelled():
                    stopping = True
                    raise AcquisitionCancelled()
                if previous is not None:
                    if (not isinstance(previous, dict) or previous.get("code") == "stale_state"
                            or previous.get("signature") != signature
                            or previous.get("stage") not in STAGES
                            or any(previous.get(name) != record[name] for name in
                                   ("scene_id", "candidate_id", "provider", "source_id"))):
                        raise ItemFailure("stale_state", "Workflow identity is inconsistent.")
                    record.update(previous)
                    if record["stage"] in {"acquired", "analyzing", "analyzed"} and not all(
                            isinstance(record.get(name), str) and record[name]
                            for name in ("local_path", "media_sha256")):
                        raise ItemFailure("stale_state", "Completed media reference is missing.")
                    if record["stage"] == "analyzed" and (
                            not isinstance(record.get("analysis_cache_key"), str) or
                            not record["analysis_cache_key"].startswith(record["media_sha256"] + ":")):
                        raise ItemFailure("stale_state", "Analysis cache reference is inconsistent.")
                if original.scene_id not in scenes:
                    raise ItemFailure("unknown_scene", "Candidate scene is not in this request.")
                candidate = original
                # Current reviews are authoritative; never use persisted acceptance.
                matching = [r for r in request.reviews if (r.scene_id, r.candidate_id) ==
                            (candidate.scene_id, candidate.candidate_id)]
                review = matching[0].normalized() if len(matching) == 1 else None
                if candidate.provider != "local" and (
                        review is None or review.decision != "accepted" or
                        (review.provider, review.source_id) != (candidate.provider, candidate.source_id)):
                    raise ItemFailure("review_required", "Matching current accepted review required.")
                prior_manifest = record.get("acquisition_manifest", "")
                if prior_manifest:
                    if candidate.acquisition_manifest and candidate.acquisition_manifest != prior_manifest:
                        raise ItemFailure("stale_state", "Acquisition reference changed.")
                    candidate = replace(candidate, acquisition_manifest=prior_manifest)
                item.candidate = candidate
                if candidate.provider == "local":
                    path = Path(candidate.preview_url or candidate.source_url).expanduser()
                    if not path.is_file() or path.is_symlink():
                        raise ItemFailure("local_unavailable", "Local media is unavailable.")
                    path = path.resolve()
                elif candidate.acquisition_manifest:
                    path = verified_candidate_path(candidate)
                    if path is None:
                        raise ItemFailure("invalid_acquisition", "Acquisition integrity validation failed.")
                    item.acquisition_reused = True
                else:
                    if record.get("local_path") or record.get("stage") in {"acquired", "analyzing", "analyzed"}:
                        raise ItemFailure("stale_state", "Acquisition reference is missing.")
                    if request.authorize_acquisition is not True:
                        raise ItemFailure("authorization_required", "Explicit acquisition authorization required.")
                    save("acquiring")
                    acquired = self.acquisition.acquire(AcquisitionRequest(candidate, review, True),
                        cancelled=cancelled, progress=lambda done, total: emit("acquiring",
                            min(100, max(0, int(done * 100 / total))) if total else None))
                    candidate = item.candidate = acquired.candidate
                    path = verified_candidate_path(candidate)
                    if path is None or path != acquired.local_path:
                        raise ItemFailure("invalid_acquisition", "Acquisition integrity validation failed.")
                    item.acquisition_reused = acquired.cache_hit
                fingerprint = fingerprint_file(path)
                if (record.get("local_path", str(path)) != str(path) or
                        record.get("media_sha256", fingerprint.sha256) != fingerprint.sha256):
                    raise ItemFailure("stale_state", "Local media identity changed.")
                item.local_path = path
                record.update(local_path=str(path), media_sha256=fingerprint.sha256,
                              acquisition_manifest=candidate.acquisition_manifest)
                save("acquired")
                check_cancel()
                save("analyzing")
                check_cancel()
                analysis = self.analysis.analyze_candidate(candidate)
                check_cancel()
                if (analysis is None or Path(analysis.source_path).resolve() != path or
                        analysis.fingerprint.sha256 != fingerprint.sha256):
                    raise ItemFailure("analysis_invalid", "Analysis did not match verified local media.")
                if analysis.metadata.duration <= 0 or analysis.metadata.width <= 0 or analysis.metadata.height <= 0:
                    raise ItemFailure("unsupported_media", "Analysis found no usable video metadata.")
                # Recheck after analysis so changed bytes cannot advance downstream.
                if fingerprint_file(path).sha256 != fingerprint.sha256 or (
                        candidate.provider != "local" and verified_candidate_path(candidate) != path):
                    raise ItemFailure("invalid_acquisition", "Media changed during analysis.")
                item.analysis = analysis
                record["analysis_cache_key"] = analysis.cache_key
                record.pop("code", None)
                record.pop("message", None)
                save("analyzed")
                self._downstream(scenes[candidate.scene_id], item, cancelled, emit)
            except AcquisitionCancelled:
                stopping = True
                item.code, item.message = "cancelled", "Workflow cancelled."
                record.update(code=item.code, message=item.message)
                try:
                    save("cancelled")
                except WorkflowStateError:
                    item.code = "state_write_failed"
            except Exception as error:
                stage = item.stage
                item.code = error.code if isinstance(error, ItemFailure) else (
                    "state_write_failed" if isinstance(error, WorkflowStateError) else
                    "acquisition_failed" if stage == "acquiring" else
                    "analysis_failed" if stage == "analyzing" else "item_failed")
                item.message = error.message if isinstance(error, ItemFailure) else "Workflow item failed safely."
                record.update(code=item.code, message=item.message)
                try:
                    save("skipped" if item.code == "authorization_required" else "failed")
                except WorkflowStateError:
                    item.stage, item.code = "failed", "state_write_failed"
        return WorkflowResult(tuple(results), store.path)

    def _downstream(self, scene, item, cancelled, emit):
        # Optional downstream failures do not erase a successful analysis.
        stage = "retrieval"
        try:
            if cancelled():
                return
            emit(stage)
            item.ranked = tuple(self.retrieval.rank_analysis(scene, item.analysis,
                metadata_text=" ".join((item.candidate.title, item.candidate.description))))
            item.downstream[stage] = "completed" if item.ranked else "no_segments"
            if self.verifier is None or not item.ranked or cancelled():
                return
            stage = "verification"
            emit(stage)
            item.verified = tuple(self.verifier.rerank(scene, list(item.ranked)))
            item.downstream[stage] = "completed" if item.verified and all(
                v.status == "verified" for v in item.verified) else "incomplete"
            if self.planner is not None and not cancelled():
                stage = "clip_planning"
                emit(stage)
                verified = [v for v in item.verified if v.status == "verified" and v.verification is not None]
                item.proposals = tuple(self.planner.propose_many(verified))
                item.downstream[stage] = "completed" if item.proposals else "no_verified_proposals"
        except Exception:
            item.downstream[stage] = "failed"
