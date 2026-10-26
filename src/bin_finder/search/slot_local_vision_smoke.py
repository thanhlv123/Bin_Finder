"""BF-S03B single-clip local Vision pilot. Zero provider calls or downloads.

DEFAULT: no file read and no Ollama inference.
Explicit --approve-local-inspection AND --approve-local-inference required
to submit three in-memory JPEG frames of ONE user-nominated local MP4 to
loopback-only Ollama. Uses the fixed harbor search-slot scenario. Result is
provisional and requires human video playback; never licenses/selects footage.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from bin_finder.models import CandidateRecord
from bin_finder.search.slot_candidates import CandidateHit, SlotSearchResult
from bin_finder.search.slot_local_vision_bridge import verify_local_vision
from bin_finder.search.slot_local_vision_gate import (
    LocalMediaForReview, prepare_local_vision,
)
from bin_finder.search.slot_metadata_rank import SlotMetadataRanker
from bin_finder.search.slot_search_smoke import synthetic_example
from bin_finder.verification.ollama_vlm import VlmConfig

_SOURCE_ID = "local:manual-single"


def _safe_number(v: float | None) -> str:
    return "unknown" if v is None else format(v, ".4f")


def _offline_rank(plan):
    slot = plan.slots[0]
    hit = CandidateHit(
        slot_id=slot.slot_id,
        beat_id=slot.beat_id,
        scene_ids=slot.scene_ids,
        matched_axes=("subject",),
        returned_order=0,
        candidate=CandidateRecord(
            candidate_id="scene_001:local:manual-single",
            scene_id=slot.scene_ids[0],
            provider="local",
            source_id=_SOURCE_ID,
            title="Human-nominated local clip - content not verified",
            duration=0.0, score=0.0,
            rights_status="unknown",
        ),
    )
    return SlotMetadataRanker().rank(
        plan, SlotSearchResult(slot.slot_id, (hit,), ()),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BF-S03B local-only single-video inference pilot (opt-in)"
    )
    parser.add_argument("--video", default="",
                        help="Existing absolute local path, NEVER a provider URL")
    parser.add_argument("--allowed-root", default="",
                        help="Existing authorized local directory containing clip")
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float, default=5.0)
    parser.add_argument(
        "--model", choices=("qwen3-vl:4b", "qwen3-vl:4b-instruct"),
        default="qwen3-vl:4b-instruct"
    )
    parser.add_argument("--approve-local-inspection", action="store_true",
                        help="Allow read-only local file validation")
    parser.add_argument("--approve-local-inference", action="store_true",
                        help="Allow exactly one Ollama inference on 3 frames")
    args = parser.parse_args(argv)

    if args.approve_local_inference and not args.approve_local_inspection:
        parser.error("Ollama inference requires both explicit opt-ins")
    if bool(args.video) != bool(args.allowed_root):
        parser.error("Provide both --video and --allowed-root")

    print("BFS03B_MODE: SINGLE_LOCAL_CLIP")
    print("BFS03B_SCENARIO: fishing-boats-enter-coastal-harbor-at-dawn")
    print("BFS03B_PROVIDER_CALLS: 0")
    print("BFS03B_MEDIA_DOWNLOADS: 0")
    print("BFS03B_CLOUD_IMAGE_UPLOADS: 0")
    print("BFS03B_VIDEO_PATH_PRINTED: False")
    print("BFS03B_LICENSE_OR_TIMELINE_APPROVED: False")

    if not args.video:
        print("BFS03B_STATUS: no-manual-media-selected")
        print("BFS03B_VERIFICATION_ATTEMPTS: 0")
        print("BFS03B_MODEL_REQUESTS_CONFIRMED: 0")
        return 0

    _, plan = synthetic_example()
    rank = _offline_rank(plan)
    chosen = LocalMediaForReview(
        provider="local", source_id=_SOURCE_ID, local_file=args.video,
        start=args.start, end=args.end,
    )
    gate = prepare_local_vision(
        rank, (chosen,), allowed_root=Path(args.allowed_root),
        approve_local_inspection=args.approve_local_inspection,
    )
    print("BFS03B_LOCAL_GATE:", gate.status)
    if not args.approve_local_inference:
        print("BFS03B_VERIFICATION_ATTEMPTS: 0")
        print("BFS03B_MODEL_REQUESTS_CONFIRMED: 0")
        print("BFS03B_STATUS: local-inference-approval-required")
        return 0
    if gate.status != "local-ready-for-inference-approval":
        print("BFS03B_VERIFICATION_ATTEMPTS: 0")
        print("BFS03B_MODEL_REQUESTS_CONFIRMED: 0")
        print("BFS03B_STATUS: no-safe-local-media")
        return 0

    run = verify_local_vision(
        plan, gate,
        approve_local_inference=True,
        config=VlmConfig(
            model=args.model, url="http://127.0.0.1:11434",
            num_ctx=8192, num_predict=4096, frames=3,
        ),
    )
    print("BFS03B_MODEL:", args.model)
    print("BFS03B_VERIFICATION_ATTEMPTS:", run.attempted_model_calls)
    print("BFS03B_MODEL_REQUESTS_CONFIRMED: unknown")
    print("BFS03B_STATUS:", run.status)
    for item in run.assessments:
        dims = item.dimensions
        print("BFS03B_ASSESSMENT:", item.status)
        print("BFS03B_SUBJECT:", _safe_number(
            dims.subject_match if dims else None))
        print("BFS03B_ACTION:", _safe_number(
            dims.action_match if dims else None))
        print("BFS03B_TIME:", _safe_number(
            dims.time_match if dims else None))
        print("BFS03B_CONTEXT_CONFLICT:", _safe_number(
            dims.context_conflict if dims else None))
        print("BFS03B_CONFIDENCE:", _safe_number(item.confidence))
        print("BFS03B_REASONS:", ",".join(item.reasons))
        print("BFS03B_HUMAN_REVIEW_REQUIRED:", item.human_review_required)
    print("BFS03B_FINAL: UNVERIFIED_HUMAN_PLAYBACK_REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
