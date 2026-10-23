"""Local-only ZB-VIDEO-01 Cuba reference evaluation runner.

This module accepts a separately supplied local editorial reference JSON file.
Do not commit user-provided YouTube video, screenshots, or benchmark narration.
No model requests without --approve-local-planner. No stock downloads/search.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from bin_finder.models import SceneRecord
from bin_finder.scene_planning import enrich_context
from bin_finder.search.query_builder import build_scene_queries
from bin_finder.search.semantic_planner import (
    LocalEditorialPlanner, OllamaEditorialConfig,
)

_ALLOWED_MATCH = {"direct", "contextual", "editorial_metaphor", "weak_indirect"}
_ALLOWED_STRENGTH = {"high", "medium", "low"}
_ID = re.compile(r"CUBA-\d{2}\Z")
_MAX_BYTES = 128_000


class ReferenceError(ValueError):
    """Invalid input reference for a private local benchmark."""


def load_reference(path: Path) -> list[dict]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_BYTES:
            raise ReferenceError("invalid-reference-file")
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise ReferenceError("unreadable-reference") from exc
    if not isinstance(document, dict) or document.get("format") != "bin_finder_cuba_reference_v1":
        raise ReferenceError("wrong-reference-format")
    beats = document.get("beats")
    if not isinstance(beats, list) or len(beats) != 15:
        raise ReferenceError("expected-15-beats")

    validated = []
    seen = set()
    previous_end = None
    for index, beat in enumerate(beats, 1):
        if not isinstance(beat, dict):
            raise ReferenceError("beat-not-object")
        beat_id = beat.get("beat_id")
        if (not isinstance(beat_id, str) or not _ID.fullmatch(beat_id)
                or beat_id != f"CUBA-{index:02d}" or beat_id in seen):
            raise ReferenceError("beat-id-invalid")
        seen.add(beat_id)

        start, end = beat.get("start_s"), beat.get("end_s")
        if not (type(start) in (int, float) and type(end) in (int, float)
                and 0 <= start < end <= 200
                and (previous_end is None or abs(start - previous_end) < 0.15)):
            raise ReferenceError("bad-beat-timestamps")
        previous_end = end
        narration = beat.get("script_excerpt")
        if not isinstance(narration, str) or not 1 <= len(narration.strip()) <= 1500:
            raise ReferenceError("bad-narration")
        if beat.get("match_type") not in _ALLOWED_MATCH:
            raise ReferenceError("bad-match-type")
        if beat.get("evidence_strength") not in _ALLOWED_STRENGTH:
            raise ReferenceError("bad-evidence-strength")
        for field in ("must_show_english", "candidate_queries_en"):
            terms = beat.get(field)
            if (not isinstance(terms, list) or not 1 <= len(terms) <= 5
                    or any(not isinstance(v, str) or not 1 <= len(v.strip()) <= 160
                           for v in terms)):
                raise ReferenceError("bad-" + field)
        validated.append(beat)
    return validated


def _scene(beat: dict, order: int) -> SceneRecord:
    narration = beat["script_excerpt"].strip()
    return SceneRecord(
        scene_id=beat["beat_id"], order=order, english_text=narration,
        context=enrich_context(narration),
    )


def evaluate_reference(
    beats: list[dict], *, start: int = 1, count: int = 1,
    approve_local_planner: bool = False, model: str | None = None,
    planner=None, inspect_rejection: bool = False,
) -> list[dict]:
    if (not 1 <= start <= len(beats)
            or not 1 <= count <= 15 or start - 1 + count > len(beats)):
        raise ReferenceError("invalid-range")
    # Only narration text is supplied to the model. Reference keywords, labels,
    # visual observations, and expected outcomes are never put in model prompts.
    full_script = " ".join(b["script_excerpt"].strip() for b in beats)
    if not 0 < len(full_script) <= 3000:
        raise ReferenceError("script-overview-limit")
    if approve_local_planner and planner is None:
        config = OllamaEditorialConfig(
            model=model if model is not None else OllamaEditorialConfig().model
        )
        planner = LocalEditorialPlanner(config)
    if not approve_local_planner and planner is not None:
        raise ReferenceError("planner-not-approved")
    if inspect_rejection and not approve_local_planner:
        raise ReferenceError("inspection-requires-local-planner-approval")

    results = []
    for n in range(start - 1, start - 1 + count):
        beat = beats[n]
        scene = _scene(beat, n + 1)
        baseline = build_scene_queries(scene, max_queries=3)
        record = {
            "beat_id": beat["beat_id"],
            "timestamp_s": [beat["start_s"], beat["end_s"]],
            "reference_match_type": beat["match_type"],
            "reference_strength": beat["evidence_strength"],
            "legacy_queries": baseline,
            "reference_editor_queries": beat["candidate_queries_en"],
            "reference_expected_visuals": beat["must_show_english"],
            "reference_is_preliminary": True,
        }
        if approve_local_planner:
            diagnostics: dict[str, object] = {}
            kwargs = {"full_script": full_script, "diagnostics": diagnostics}
            if inspect_rejection:
                kwargs["inspect_rejection"] = True
            proposed = planner.propose(scene, **kwargs)
            record["planner_status"] = diagnostics.get("reason", "unknown")
            record["planner_diagnostics"] = diagnostics
            record["planner_queries"] = proposed["queries"] if proposed else baseline
            record["used_legacy_fallback"] = proposed is None
            record["model_visual_goal"] = proposed["visual_goal"] if proposed else ""
            record["model_must_show"] = proposed["must_show"] if proposed else []
            record["model_must_not_show"] = proposed["must_not_show"] if proposed else []
            record["model_uncertainty"] = proposed["uncertainty"] if proposed else ""
            record["model_evidence_type"] = proposed.get("evidence_type", "unknown") if proposed else "unknown"
            record["model_scene_anchor"] = proposed.get("scene_anchor", "") if proposed else ""
            record["planner_no_match"] = bool(
                proposed is not None and proposed.get("evidence_type") == "no_match"
            )
        else:
            record["planner_status"] = "NOT_RUN_NO_APPROVAL"
        results.append(record)
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ZB-VIDEO-01 private script-to-footage reference")
    parser.add_argument("--reference", type=Path, required=True,
                        help="Path to the separately supplied Cuba reference JSON")
    parser.add_argument("--start", type=int, default=1, help="1-based first beat")
    parser.add_argument("--count", type=int, default=1, help="1..15 beats; default 1")
    parser.add_argument("--approve-local-planner", action="store_true",
                        help="Opt in to one localhost Ollama request per selected beat")
    parser.add_argument("--model", type=str, default=None,
                        help="Optional preinstalled local Ollama model tag")
    parser.add_argument("--inspect-rejected", action="store_true",
                        help="Opt in to bounded, locally printed rejected model plan fields; "
                             "never includes whole script or model thinking")
    args = parser.parse_args(argv)
    try:
        beats = load_reference(args.reference)
        results = evaluate_reference(
            beats, start=args.start, count=args.count,
            approve_local_planner=args.approve_local_planner, model=args.model,
            inspect_rejection=args.inspect_rejected,
        )
    except (ReferenceError, ValueError) as exc:
        print("ZB_VIDEO_ERROR:", str(exc))
        return 2
    for record in results:
        print("ZB_VIDEO_RESULT:", json.dumps(record, ensure_ascii=False))
    print("ZB_VIDEO_REFERENCE_ONLY: no provider search or footage accuracy measured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
