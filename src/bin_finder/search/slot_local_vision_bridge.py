"""BF-S03B Phase 1: explicitly approved local Ollama vision bridge.

Reuses F021 frame sampler + loopback-only verifier. No provider calls,
media downloads, automatic selection, licensing approval or GUI mutation.

Every score is uncalibrated model output about 3 still frames. Ambiguous
movement into a harbor is a temporal assertion requiring human playback.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

from bin_finder.models import SceneContext, SceneRecord
from bin_finder.retrieval.models import RetrievalUnit
from bin_finder.search.slot_local_vision_gate import (
    LocalVisionGateResult, LocalVisionGateError, PreparedVisionUnit,
)
from bin_finder.search.visual_search_contract import SemanticSearchPlan
from bin_finder.verification.models import VerificationDimensions
from bin_finder.verification.ollama_vlm import (
    OllamaVisionVerifier, VlmConfig, validate_loopback_url,
)


@dataclass(frozen=True)
class LocalVisionAssessment:
    slot_id: str
    provider: str
    source_id: str
    status: str
    dimensions: VerificationDimensions | None = None
    confidence: float | None = None
    reasons: tuple[str, ...] = ()
    human_review_required: bool = True
    # Keep local source path and arbitrary VLM free text OUT of reports.


@dataclass(frozen=True)
class LocalVisionRun:
    slot_id: str
    status: str
    assessments: tuple[LocalVisionAssessment, ...] = ()
    attempted_model_calls: int = 0
    provider_calls: int = 0
    downloaded_media: int = 0
    timeline_approved: bool = False


def _scene_from_visual_slot(slot) -> SceneRecord:
    queries = {item.axis: item.text for item in slot.queries}
    # Narrative source_text can be figurative; instruct model to check the
    # editorial visual_brief and must_show/avoid criteria instead.
    return SceneRecord(
        scene_id=slot.scene_ids[0],
        order=1,
        english_text=slot.visual_brief,
        context=SceneContext(
            subject=(slot.visual_brief,),
            action=(queries["action"],),
            location=slot.required_entities[:8],
            objects=slot.must_show[:8],
            avoid=slot.must_not_show[:8],
        ),
    )


def verify_local_vision(
    plan: SemanticSearchPlan,
    gate: LocalVisionGateResult,
    *,
    approve_local_inference: bool = False,
    config: VlmConfig | None = None,
    _test_verifier=None,
) -> LocalVisionRun:
    """Never calls Ollama unless caller explicitly approves SECOND gate.

    _test_verifier is for injected network-free unit fakes only; production
    always uses a built-in validated loopback-only OllamaVisionVerifier.
    """
    if not isinstance(plan, SemanticSearchPlan) or not isinstance(
        gate, LocalVisionGateResult
    ) or type(approve_local_inference) is not bool:
        raise LocalVisionGateError("invalid-vision-bridge-input")
    matched = [slot for slot in plan.slots if slot.slot_id == gate.slot_id]
    if len(matched) != 1 or matched[0].action != "search":
        raise LocalVisionGateError("invalid-vision-slot")
    if (len(gate.prepared) > 5
            or any(not isinstance(item, PreparedVisionUnit)
                   or item.slot_id != gate.slot_id for item in gate.prepared)
            or len({item.key for item in gate.prepared}) != len(gate.prepared)):
        raise LocalVisionGateError("invalid-prepared-media")
    if not approve_local_inference:
        return LocalVisionRun(gate.slot_id, "local-inference-approval-required")
    if gate.status != "local-ready-for-inference-approval" or not gate.prepared:
        return LocalVisionRun(gate.slot_id, "no-approved-local-media")

    cfg = config or VlmConfig(num_ctx=8192, num_predict=4096, frames=3)
    cfg.validate()
    validate_loopback_url(cfg.url)
    if cfg.mode == "off":
        return LocalVisionRun(gate.slot_id, "local-vision-mode-off")

    verifier = _test_verifier if _test_verifier is not None else OllamaVisionVerifier(cfg)
    slot = matched[0]
    scene = _scene_from_visual_slot(slot)
    assessments: list[LocalVisionAssessment] = []
    for n, prepared in enumerate(gate.prepared, 1):
        unit = RetrievalUnit(
            unit_id=f"{gate.slot_id}:review:{n}",
            source_path=str(prepared.source_file),
            start=prepared.start, end=prepared.end,
        )
        try:
            returned = verifier.verify(scene, [unit])
            evidence = returned[0] if len(returned) == 1 else None
            if evidence is not None and evidence.unit_id != unit.unit_id:
                evidence = None
        except Exception:
            # No raw model/path/HTTP exceptions in reports. A failed model
            # never becomes a heuristic or verified result.
            evidence = None
        if evidence is None:
            assessments.append(LocalVisionAssessment(
                slot_id=gate.slot_id, provider=prepared.provider,
                source_id=prepared.source_id,
                status="vision-unavailable-or-abstained",
                reasons=("no-usable-vision-evidence",),
            ))
            continue

        dims = evidence.dimensions.normalized()
        conf = evidence.confidence
        if (not isinstance(conf, (int, float)) or not math.isfinite(conf)
                or not 0.0 <= conf <= 1.0):
            assessments.append(LocalVisionAssessment(
                slot_id=gate.slot_id, provider=prepared.provider,
                source_id=prepared.source_id,
                status="vision-unavailable-or-abstained",
                reasons=("invalid-model-confidence",),
            ))
            continue

        notes = ["model-frame-evidence-not-independent-fact"]
        if dims.subject_match is None:
            notes.append("subject-not-assessed")
        if dims.action_match is None:
            notes.append("action-not-assessed")
        if dims.time_match is None:
            notes.append("time-of-day-not-assessed")
        if slot.required_entities:
            notes.append("required-entities-need-external-evidence")
        if slot.evidence_type == "direct":
            notes.append("temporal-action-requires-human-playback")
        if dims.context_conflict is not None and dims.context_conflict >= .7:
            notes.append("possible-must-not-show-conflict")
        status = (
            "vision-inconclusive-human-review"
            if dims.subject_match is None or dims.action_match is None
            else "vision-provisional-human-review"
        )
        assessments.append(LocalVisionAssessment(
            slot_id=gate.slot_id, provider=prepared.provider,
            source_id=prepared.source_id, status=status,
            dimensions=dims, confidence=float(conf),
            reasons=tuple(notes),
        ))
    return LocalVisionRun(
        slot_id=gate.slot_id, status="human-review-required",
        assessments=tuple(assessments),
        attempted_model_calls=len(gate.prepared),
    )
