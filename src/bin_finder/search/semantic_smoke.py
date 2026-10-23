"""Explicit opt-in local Ollama query quality smoke for ZB-01 (not pytest/CI)."""
from __future__ import annotations

import argparse

from bin_finder.models import SceneContext, SceneRecord
from bin_finder.search.query_builder import build_scene_queries
from bin_finder.search.semantic_planner import LocalEditorialPlanner

SCRIPT = (
    "At ten at night, office lights still glow in Lujiazui, Shanghai. "
    "This shot alone does not prove that people are working overtime."
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ZB-01 local-only editorial query demonstration")
    parser.add_argument(
        "--approve-local-planner", action="store_true",
        help="Explicitly authorize one text-only HTTP request to local Ollama.",
    )
    args = parser.parse_args(argv)
    if not args.approve_local_planner:
        print("SKIPPED_ZB01_NOT_APPROVED")
        return 0

    scene = SceneRecord(
        scene_id="scene_001", order=1, english_text=SCRIPT,
        context=SceneContext(keywords=("Lujiazui office lights",)),
    )
    legacy = build_scene_queries(scene, max_queries=3)
    proposed = LocalEditorialPlanner().propose(scene, full_script=SCRIPT)
    print("ZB01_BASELINE_QUERIES:", repr(legacy))
    if proposed is None:
        print("ZB01_FALLBACK: no valid local Ollama editorial result")
        return 2
    print("ZB01_PROPOSED_QUERIES:", repr(proposed["queries"]))
    print("ZB01_MUST_SHOW:", repr(proposed["must_show"]))
    print("ZB01_MUST_NOT_SHOW:", repr(proposed["must_not_show"]))
    print("ZB01_UNCERTAINTY:", str(proposed["uncertainty"]))
    print("ZB01_VALID_STRUCTURED_RESULT; real footage relevance NOT tested")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
