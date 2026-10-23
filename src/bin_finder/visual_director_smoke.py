"""ZB-02B synthetic three-genre storyboard smoke.

Safe by default: without --approve-local-planner, NO model request is made.
No files are read or written; all scripts are invented synthetic examples.
"""
from __future__ import annotations

import argparse
import json

from bin_finder.models import SceneRecord
from bin_finder.visual_director import LocalVisualDirector
from bin_finder.visual_plan_audit import audit_visual_story_plan
from bin_finder.visual_planning import parse_visual_story_plan

SYNTHETIC_GENRES: dict[str, tuple[str, ...]] = {
    "travel": (
        "In a coastal town, small fishing boats enter the harbor at sunrise.",
        "Workers unload fish and mend their nets beside the pier.",
        "But beyond the waterfront the neighborhood has a different rhythm.",
        "Families gather at the morning market to buy food.",
    ),
    "history": (
        "Ancient stone bridges connected the two sides of this valley.",
        "Merchants crossed the bridge carrying baskets and cloth.",
        "The trade routes changed over the following centuries.",
        "Today, the surviving bridge remains a reminder of that history.",
    ),
    "economy": (
        "At night a city's office towers remain brightly illuminated.",
        "Workers travel home on crowded trains after long shifts.",
        "Yet city lights alone cannot measure a worker's real wage.",
        "A chart would need independently verified salary and price data.",
    ),
}


def synthetic_scenes(genre: str) -> tuple[SceneRecord, ...]:
    return tuple(
        SceneRecord(scene_id=f"scene_{i:03d}", order=i, english_text=sentence)
        for i, sentence in enumerate(SYNTHETIC_GENRES[genre], 1)
    )


# Offline editorial examples are NOT a ground-truth label set. They are only
# used to demonstrate coverage, multi-scene shots and non-search strategies.
def _search(sid: str, block: str, scene_ids: list[str],
            goal: str, queries: list[str], evidence: str) -> dict:
    return {
        "shot_id": sid, "block_id": block, "scene_ids": scene_ids,
        "strategy": "search", "evidence_type": evidence,
        "visual_goal": goal, "queries": queries, "hold_from_shot_id": None,
    }


def _nonsearch(sid: str, block: str, scene_ids: list[str],
               strategy: str, goal: str, hold_from: str | None = None) -> dict:
    return {
        "shot_id": sid, "block_id": block, "scene_ids": scene_ids,
        "strategy": strategy, "evidence_type": "not_applicable",
        "visual_goal": goal, "queries": [],
        "hold_from_shot_id": hold_from,
    }


def editorial_example(genre: str) -> dict:
    first = {
        "block_id": "b1", "scene_ids": ["scene_001", "scene_002"],
        "role": "establish", "summary": "Introduce physical setting",
        "visual_purpose": "Establish concrete context without excessive cuts",
    }
    second = {
        "block_id": "b2", "scene_ids": ["scene_003", "scene_004"],
        "role": "explain", "summary": "Shift in meaning and narrative emphasis",
        "visual_purpose": "Preserve continuity, avoid claiming proof from stock",
    }
    if genre == "travel":
        shots = [
            _search("s1", "b1", ["scene_001", "scene_002"],
                    "Active coastal harbor", ["fishing boats sunrise harbor"], "contextual"),
            _nonsearch("s2", "b2", ["scene_003"], "transition",
                       "Contrast waterfront and everyday neighborhood"),
            _search("s3", "b2", ["scene_003", "scene_004"],
                    "Morning neighborhood market", ["coastal town produce market"], "contextual"),
        ]
    elif genre == "history":
        shots = [
            _search("s1", "b1", ["scene_001", "scene_002"],
                    "Historic stone bridge", ["old stone bridge river valley"], "contextual"),
            _nonsearch("s2", "b2", ["scene_003"], "hold",
                       "Keep historic bridge as narrator discusses change", "s1"),
            _search("s3", "b2", ["scene_004"],
                    "Surviving bridge today", ["historic stone bridge today"], "contextual"),
        ]
    else:
        shots = [
            _search("s1", "b1", ["scene_001", "scene_002"],
                    "Illuminated office district at night",
                    ["city office buildings illuminated night"], "contextual"),
            _nonsearch("s2", "b2", ["scene_003"], "hold",
                       "Continue office footage without claiming salary evidence", "s1"),
            _nonsearch("s3", "b2", ["scene_004"], "graphic",
                       "Placeholder: chart requires verified wage and price sources"),
        ]
    return {
        "format": "bin_finder_visual_plan_v1",
        "plan_id": "zb02_synthetic_" + genre,
        "blocks": [first, second],
        "shots": shots,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ZB-02B three-genre synthetic visual planning")
    parser.add_argument("--genre", choices=tuple(SYNTHETIC_GENRES), required=True)
    parser.add_argument("--approve-local-planner", action="store_true",
                        help="Explicitly allow ONE localhost Ollama request on a synthetic script")
    args = parser.parse_args(argv)
    scenes = synthetic_scenes(args.genre)
    if not args.approve_local_planner:
        plan = parse_visual_story_plan(editorial_example(args.genre), scenes)
        print("ZB02_STATUS: EDITORIAL_EXAMPLE_ONLY_NO_MODEL")
    else:
        diagnostics: dict[str, object] = {}
        plan = LocalVisualDirector().propose(
            scenes, plan_id="zb02_synthetic_" + args.genre, diagnostics=diagnostics
        )
        print("ZB02_DIAGNOSTICS:", json.dumps(diagnostics, ensure_ascii=False))
        if plan is None:
            print("ZB02_STATUS: INVALID_MODEL_PLAN_NO_PROVIDER_REQUESTS")
            return 2
        print("ZB02_STATUS: VALID_MODEL_STRUCTURE_NOT_FOOTAGE_ACCURACY")
    print("ZB02_GENRE:", args.genre)
    print("ZB02_SCENES:", len(scenes))
    print("ZB02_BLOCKS:", len(plan.blocks))
    print("ZB02_SHOTS:", len(plan.shots))
    print("ZB02_SEARCH_REQUESTS:", len(plan.search_requests()))
    print("ZB02_AUDIT:", json.dumps(
        audit_visual_story_plan(plan, scenes).to_mapping(), ensure_ascii=False
    ))
    print("ZB02_PLAN:", json.dumps(plan.to_mapping(), ensure_ascii=False))
    print("ZB02_RESEARCH_ONLY: no footage/provider/GUI or timing operations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
