"""BF-S04A.1 manual single-slot AI shot planner trial.

Default is dry-run: NO Ollama / provider / media call. With explicit consent,
ONE French Gaspard excerpt and its existing BF-S01 VisualSlot can be passed to
the configured local Qwen3-VL instruct TEXT interface. Result is strictly
validated and optional output file is user-chosen with exclusive creation.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path

from bin_finder.search.editorial_local_model import (
    LocalEditorialConfig, OllamaLocalEditorialPlanner,
)
from bin_finder.search.editorial_shot_smoke import source_and_base
from bin_finder.search.visual_search_contract import script_digest


def selected_excerpt(number: int):
    """Reuse an editor-authored BF-S01 slot; do not claim AI planned this slot."""
    scenes, base = source_and_base()
    index = number - 1
    scene = replace(scenes[index], order=1)
    selected = replace(
        base, source_digest=script_digest((scene,)),
        beats=(base.beats[index],), slots=(base.slots[index],),
    )
    return (scene,), selected


def _safe_new_json_path(value: str) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if (not candidate.is_absolute() or candidate.suffix.casefold() != ".json"
            or candidate.exists() or candidate.is_symlink()):
        raise ValueError("invalid-output-target")
    # Do not write through symlinked/junction ancestors; no overwrites.
    try:
        ancestors = (candidate.parent, *candidate.parent.parents)
        if (not candidate.parent.is_dir()
                or any(p.is_symlink() or
                       getattr(p, "is_junction", lambda: False)()
                       for p in ancestors)):
            raise ValueError("unsafe-output-folder")
    except OSError:
        raise ValueError("unsafe-output-folder") from None
    return candidate


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="BF-S04A.1 single-slot local editorial AI smoke, dry-run by default"
    )
    parser.add_argument("--slot", type=int, choices=range(1, 8), default=2,
                        metavar="{1,2,3,4,5,6,7}")
    parser.add_argument("--model", choices=(
        "qwen3-vl:4b-instruct", "qwen3-vl:4b",
    ), default="qwen3-vl:4b-instruct")
    parser.add_argument("--output-json", default="",
                        help="Optional absolute new JSON filepath; no overwrite")
    parser.add_argument("--approve-local-model-call", action="store_true",
                        help="Explicitly permit exactly one local Ollama text request")
    args = parser.parse_args(argv)

    print("BFS04A1_MODE: ONE_SLOT_LOCAL_OLLAMA_TEXT_PILOT")
    print("BFS04A1_EDITORIAL_BASE: USER_SCRIPT_EDITOR_AUTHORED_BF_S01")
    print("BFS04A1_SELECTED_SLOT:", args.slot)
    print("BFS04A1_PROVIDER_CALLS: 0")
    print("BFS04A1_MEDIA_DOWNLOADS: 0")
    print("BFS04A1_CLOUD_UPLOADS: 0")
    print("BFS04A1_VISION_FRAME_CALLS: 0")
    print("BFS04A1_LICENSE_OR_TIMELINE_APPROVED: False")
    print("BFS04A1_MODEL:", args.model)

    scenes, base = selected_excerpt(args.slot)
    if not args.approve_local_model_call:
        print("BFS04A1_STATUS: local-model-approval-required")
        print("BFS04A1_MODEL_CALL_ATTEMPTS: 0")
        print("BFS04A1_JSON_WRITTEN: False")
        return 0
    try:
        output = _safe_new_json_path(args.output_json)
    except ValueError as exc:
        print("BFS04A1_STATUS: invalid-local-output-target")
        print("BFS04A1_ERROR_CODE:", str(exc))
        print("BFS04A1_MODEL_CALL_ATTEMPTS: 0")
        return 2

    client = OllamaLocalEditorialPlanner(LocalEditorialConfig(
        model=args.model, url="http://127.0.0.1:11434",
        num_ctx=8192, num_predict=4096,
    ))
    result = client.propose(base, scenes, approve_local_model_call=True)

    print("BFS04A1_STATUS:", result.status)
    print("BFS04A1_MODEL_CALL_ATTEMPTS:", result.calls_attempted)
    print("BFS04A1_MODEL_HTTP_REQUESTS_CONFIRMED:", result.confirmed_http_requests)
    print("BFS04A1_REJECT_REASON:", result.reject_reason or "none")
    print("BFS04A1_JSON_VALIDATED:", result.plan is not None)
    print("BFS04A1_LANGUAGE_LABELS_NORMALIZED:", result.normalized_language_labels)

    if result.plan is None:
        print("BFS04A1_JSON_WRITTEN: False")
        return 0
    print("BFS04A1_SHOTS:", len(result.plan.shots))
    print("BFS04A1_TOTAL_TARGET_SECONDS:", sum(
        item.target_duration_seconds for item in result.plan.shots
    ))
    for shot in result.plan.shots:
        print(
            "BFS04A1_SHOT:",
            shot.shot_id,
            "seconds=" + str(shot.target_duration_seconds),
            "kind=" + shot.asset_evidence_type,
            "route=" + shot.source_route,
        )
    if output is None:
        print("BFS04A1_JSON_WRITTEN: False")
        print("BFS04A1_STATUS_NOTE: no-output-file-requested")
        return 0
    try:
        with output.open("x", encoding="utf-8") as target:
            json.dump(result.plan.to_mapping(), target, ensure_ascii=False, indent=2)
            target.write("\n")
    except OSError:
        print("BFS04A1_JSON_WRITTEN: False")
        print("BFS04A1_STATUS_NOTE: local-output-write-failed")
        return 2
    print("BFS04A1_JSON_WRITTEN: True")
    print("BFS04A1_FINAL: HUMAN_EDITORIAL_AND_RIGHTS_REVIEW_REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
