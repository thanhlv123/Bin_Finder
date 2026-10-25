"""BF-S02 safe single-slot smoke. By default this does NOT call providers.

The sample story and visuals are invented, not real user narration.
Explicit --approve-provider-calls permits only a bounded provider search;
no assets are downloaded and no frames are uploaded or decoded.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from bin_finder.models import SceneRecord
from bin_finder.search.visual_search_contract import (
    FORMAT, parse_semantic_search_plan, script_digest,
)


def synthetic_example():
    scene = SceneRecord(
        scene_id="scene_001", order=1,
        english_text="At dawn fishing boats enter the coastal harbor.",
    )
    plan = {
        "format": FORMAT,
        "plan_id": "bf_s02_synthetic_single",
        "source_digest": script_digest((scene,)),
        "beats": [{
            "beat_id": "beat1", "scene_ids": ["scene_001"],
            "meaning": "Introduce the working harbor at daybreak",
            "anchor_text": scene.english_text,
            "section_context": "Establish a coastal working location",
            "metaphor_note": "",
        }],
        "slots": [{
            "slot_id": "slot1", "beat_id": "beat1",
            "scene_ids": ["scene_001"], "role": "establish",
            "action": "search", "evidence_type": "contextual",
            "entity_policy": "contextual",
            "source_text": scene.english_text,
            "visual_brief": "Fishing boats entering a harbor at sunrise",
            "must_show": ["boats", "water", "harbor"],
            "must_not_show": ["talking head", "indoor studio"],
            "required_entities": [],
            "queries": [
                {"axis": "subject", "text": "fishing boats harbor"},
                {"axis": "moment", "text": "coastal harbor at dawn"},
                {"axis": "action", "text": "fishing vessels entering harbor"},
            ],
            "reuse_from_slot_id": None,
            "uncertainty": "Stock may depict a different harbor.",
        }],
    }
    return (scene,), parse_semantic_search_plan(plan, (scene,))


def _safe_label(value: str, limit: int = 95) -> str:
    return " ".join("".join(c for c in value[:limit] if c.isprintable()).split())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BF-S02 single-slot candidate discovery pilot (no downloads)"
    )
    parser.add_argument("--provider", choices=("pexels", "pixabay", "local"),
                        default="pexels")
    parser.add_argument("--project-root", default=".",
                        help="Directory with optional config/providers.local.json")
    parser.add_argument(
        "--approve-provider-calls", action="store_true",
        help="Explicitly authorize up to 3 configured-provider search calls",
    )
    args = parser.parse_args(argv)
    scenes, plan = synthetic_example()
    req = plan.search_requests()[0]
    print("BFS02_MODE:", "APPROVED_PROVIDER_PILOT" if args.approve_provider_calls
          else "OFFLINE_PLAN_ONLY")
    print("BFS02_SLOT:", req.slot_id)
    print("BFS02_QUERIES:", ", ".join(
        q.axis + ": " + q.text for q in req.queries
    ))
    print("BFS02_NO_DOWNLOAD_OR_VISION: True")

    if not args.approve_provider_calls:
        print("BFS02_STATUS: NO_PROVIDER_CALLS")
        return 0

    from bin_finder.provider_config import ProviderConfig
    from bin_finder.providers.registry import ProviderRegistry
    from bin_finder.search.slot_candidates import (
        SlotCandidateSearch, SlotSearchOptions,
    )

    # Only explicit opt-in reaches this block or loads private provider config.
    registry = ProviderRegistry.from_config(
        ProviderConfig.load(Path(args.project_root))
    )
    results = SlotCandidateSearch(registry).search(
        plan, scenes,
        SlotSearchOptions(
            (args.provider,), per_query_limit=5,
            max_candidates_per_slot=10, max_calls=3,
        ),
        approve_provider_calls=True,
    )
    item = results.slot("slot1")
    print("BFS02_PROVIDER_CALLS:", results.provider_calls)
    print("BFS02_SLOT_STATUS:", item.status)
    print("BFS02_UNVERIFIED_CANDIDATES:", len(item.hits))
    for attempt in item.attempts:
        print("BFS02_ATTEMPT:", attempt.axis, attempt.status,
              attempt.received)
    # No signed/temporary URLs, raw response payload, credential or user data.
    for hit in item.hits[:5]:
        print("BFS02_CANDIDATE:", _safe_label(hit.candidate.title),
              "source=" + _safe_label(hit.candidate.source_id, 80),
              "axes=" + ",".join(hit.matched_axes))
    print("BFS02_STATUS: COMPLETED_UNVERIFIED_NO_SELECTION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
