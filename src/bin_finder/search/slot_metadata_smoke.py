"""BF-S03A metadata-only research pilot. Default is OFFLINE and synthetic.

Live research requires BOTH --live-providers and --approve-provider-calls.
At most 6 source requests (3 axes × 2 providers), no downloads/frames/AI.
Provider IDs are allowlisted; NO HTTP URLs, secrets or raw API exceptions.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from bin_finder.models import CandidateRecord
from bin_finder.search.slot_candidates import (
    CandidateHit, SlotCandidateSearch, SlotSearchOptions, SlotSearchResult,
)
from bin_finder.search.slot_metadata_rank import SlotMetadataRanker
from bin_finder.search.slot_search_smoke import synthetic_example

_SOURCE_ID = re.compile(r"^(?:pexels|pixabay):[0-9]{1,20}$")


def _safe_id(source_id: str) -> str:
    return source_id if _SOURCE_ID.fullmatch(source_id) else "redacted-identifier"


def _synthetic_pool(plan) -> SlotSearchResult:
    examples = (
        ("pexels", "pexels:10020348",
         "Fishing boat sailing in the sea toward coastal harbor at dawn"),
        ("pexels", "pexels:19637496",
         "Fishing boats docked in the water at harbor"),
        ("pixabay", "pixabay:330501",
         "Industrial night photography oil refinery blue hour cityscape"),
        ("pixabay", "pixabay:12127",
         "Dawn sunrise beach clouds early morning"),
        ("pixabay", "pixabay:6412",
         "Fishing boat harbor sea water ocean port"),
    )
    slot = plan.slots[0]
    hits = tuple(
        CandidateHit(
            slot_id=slot.slot_id, beat_id=slot.beat_id,
            scene_ids=slot.scene_ids, returned_order=i,
            matched_axes=("subject",),
            candidate=CandidateRecord(
                candidate_id=f"scene_001:{provider}:{i}",
                scene_id="scene_001", provider=provider,
                source_id=ident, title=title,
                duration=12.0, score=0, rights_status="unknown",
                resolution="1920x1080",
            ),
        ) for i, (provider, ident, title) in enumerate(examples)
    )
    return SlotSearchResult(slot.slot_id, hits, ())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BF-S03A metadata rank pilot")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--live-providers", action="store_true",
                        help="Use configured Pexels + Pixabay, never download media")
    parser.add_argument("--approve-provider-calls", action="store_true",
                        help="Explicitly allow at most six provider searches")
    args = parser.parse_args(argv)
    if args.live_providers != args.approve_provider_calls:
        parser.error("Live search requires both opt-in flags")

    scenes, plan = synthetic_example()
    provider_calls = 0
    if args.live_providers:
        from bin_finder.provider_config import ProviderConfig
        from bin_finder.providers.registry import ProviderRegistry

        config = ProviderConfig.load(Path(args.project_root))
        registry = ProviderRegistry.from_config(config)
        run = SlotCandidateSearch(registry).search(
            plan, scenes,
            SlotSearchOptions(
                ("pexels", "pixabay"), per_query_limit=5,
                max_candidates_per_slot=20, max_calls=6,
            ),
            approve_provider_calls=True,
        )
        provider_calls = run.provider_calls
        results = run.slot("slot1")
        mode = "LIVE_PROVIDER_METADATA_ONLY"
    else:
        results = _synthetic_pool(plan)
        mode = "OFFLINE_SYNTHETIC_NO_PROVIDER_CALLS"

    ranked = SlotMetadataRanker().rank(plan, results)
    print("BFS03A_MODE:", mode)
    print("BFS03A_PROVIDER_CALLS:", provider_calls)
    print("BFS03A_SLOT:", ranked.slot_id)
    print("BFS03A_INPUT_CANDIDATES:", len(results.hits))
    print("BFS03A_UNIQUE_DISCOVERED:", results.unique_discovered)
    print("BFS03A_STATUS:", ranked.status)
    print("BFS03A_FRAME_OR_LICENSING_VERIFIED: False")
    print("BFS03A_NO_DOWNLOAD_OR_VISION: True")
    for i, item in enumerate(ranked.ranked, 1):
        d = item.evidence
        print(
            "BFS03A_RANK:", i,
            "source=" + _safe_id(item.hit.candidate.source_id),
            "score=" + str(item.score),
            "priority=" + item.priority,
            "subject=" + str(d.subject),
            "moment=" + str(d.moment),
            "action=" + str(d.action),
            "action_signal=" + d.action_signal,
            "quality=" + str(d.quality_points),
            "reasons=" + ",".join(item.reasons),
        )
    print("BFS03A_TOP5_REVIEW:", ",".join(
        _safe_id(item.hit.candidate.source_id)
        for item in ranked.top_for_review()
    ))
    print("BFS03A_FINAL: METADATA_ONLY_HUMAN_REVIEW_REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
