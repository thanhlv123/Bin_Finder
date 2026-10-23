"""Standalone ZB-03A human-review demo. No changes to Bin Finder main GUI.

Launch with: python -m bin_finder.timeline_review_demo --genre travel
All candidates are synthetic titles until the user explicitly chooses a local
file in the UI. Nothing is downloaded, rendered, persisted, or F014-approved.
"""
from __future__ import annotations

import argparse
import sys

from bin_finder.draft_timeline import DraftCandidate, build_draft_timeline
from bin_finder.visual_director_smoke import (
    SYNTHETIC_GENRES, editorial_example, synthetic_scenes,
)
from bin_finder.visual_planning import parse_visual_story_plan


def build_demo(genre: str = "travel"):
    scenes = synthetic_scenes(genre)
    plan = parse_visual_story_plan(editorial_example(genre), scenes)
    candidates = {}
    for shot in plan.shots:
        if shot.strategy == "search":
            candidates[shot.shot_id] = tuple(
                DraftCandidate(
                    candidate_id=f"demo_{shot.shot_id}_{idx}",
                    title=f"Giả lập {idx}: {query[:125]}",
                )
                for idx, query in enumerate(shot.queries, 1)
            )
            # Always give reviewer a second alternative in this synthetic
            # demonstration, even if AI requested only one query.
            if len(candidates[shot.shot_id]) == 1:
                candidates[shot.shot_id] += (
                    DraftCandidate(
                        candidate_id=f"demo_{shot.shot_id}_alt",
                        title=f"Giả lập thay thế: {shot.visual_goal[:110]}",
                    ),
                )
    draft = build_draft_timeline(plan, scenes, candidates)
    return scenes, plan, draft


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ZB-03A independent human review timeline"
    )
    parser.add_argument("--genre", choices=tuple(SYNTHETIC_GENRES),
                        default="travel")
    parser.add_argument(
        "--headless", action="store_true",
        help="Print a synthetic state summary, without importing Qt",
    )
    args = parser.parse_args(argv)
    scenes, plan, draft = build_demo(args.genre)
    if args.headless:
        print("ZB03A_STATUS: SYNTHETIC_DRAFT_ONLY")
        print("ZB03A_GENRE:", args.genre)
        print("ZB03A_SCENES:", len(scenes))
        print("ZB03A_SHOTS:", len(draft.items))
        print("ZB03A_COUNTS:", draft.counts())
        print("ZB03A_NO_VIDEO_EXPORT: True")
        return 0
    from PyQt6.QtWidgets import QApplication
    from bin_finder.timeline_review_gui import TimelineReviewWindow
    app = QApplication.instance() or QApplication(sys.argv)
    window = TimelineReviewWindow(scenes, plan, draft)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
