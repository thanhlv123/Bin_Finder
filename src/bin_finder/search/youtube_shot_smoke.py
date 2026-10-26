"""BF-S06 opt-in YouTube reference discovery for an existing local Shot Plan.

Default dry-run makes ZERO HTTP requests. Search only reads official YouTube
Data API metadata; even approved search can never download video or clips.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bin_finder.provider_config import ProviderConfig
from bin_finder.providers.youtube import YouTubeProvider
from bin_finder.search.editorial_local_smoke import selected_excerpt
from bin_finder.search.editorial_local_model import parse_local_editorial_reply
from bin_finder.search.youtube_shot_discovery import discover_youtube_for_shot


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="BF-S06 metadata-only YouTube editorial shot search pilot",
    )
    p.add_argument("--plan-json", required=True)
    p.add_argument("--project-root", default=".")
    p.add_argument("--approve-youtube-api-search", action="store_true")
    p.add_argument("--include-standard-license-references", action="store_true",
                   help="Find all YouTube license types, for reference review only")
    p.add_argument("--max-queries", type=int, default=2)
    p.add_argument("--max-results", type=int, default=5)
    args = p.parse_args(argv)

    print("BFS06_MODE: YOUTUBE_API_METADATA_ONLY")
    print("BFS06_AUDIOVISUAL_DOWNLOADS: 0")
    print("BFS06_VIDEO_EXTRACTIONS: 0")
    print("BFS06_CLOUD_FRAME_UPLOADS: 0")
    print("BFS06_CONTENT_OR_RIGHTS_APPROVED: False")
    print("BFS06_REFERENCE_LICENSES_ONLY: True")

    if not args.approve_youtube_api_search:
        print("BFS06_STATUS: approval-required")
        print("BFS06_SEARCH_ATTEMPTS: 0")
        return 0
    path = Path(args.plan_json)
    if (not path.is_absolute() or not path.is_file() or path.is_symlink()
            or path.suffix.lower() != ".json"
            or path.stat().st_size > 262144):
        print("BFS06_STATUS: invalid-local-shot-plan")
        return 2
    try:
        raw = path.read_text(encoding="utf-8")
        scenes, base = selected_excerpt(2)
        plan = parse_local_editorial_reply(raw, base, scenes)
        shot = plan.shots[0]
    except (OSError, UnicodeError, ValueError):
        print("BFS06_STATUS: invalid-local-shot-plan")
        return 2
    # Only a single bounded pilot shot. No implicit all-video/account crawling.
    try:
        cfg = ProviderConfig.load(Path(args.project_root))
        result = discover_youtube_for_shot(
            shot, YouTubeProvider(cfg.youtube_api_key),
            approve_youtube_api_search=True,
            max_queries=args.max_queries,
            max_results=args.max_results,
            creative_commons_filter=not args.include_standard_license_references,
        )
    except ValueError:
        print("BFS06_STATUS: invalid-search-arguments")
        return 2
    print("BFS06_SHOT_ID:", result.shot_id)
    print("BFS06_STATUS:", result.status)
    print("BFS06_SEARCH_ATTEMPTS:", result.search_attempts)
    print("BFS06_RESULTS:", len(result.hits))
    for item in result.hits:
        print("BFS06_REFERENCE_ID:", item.video_id)
        print("BFS06_WATCH_URL:", item.watch_url)
        print("BFS06_METADATA_LICENSE:", item.metadata_license)
        print("BFS06_ACQUISITION_ALLOWED:", item.acquisition_allowed)
        print("BFS06_CLIP_EXPORT_ALLOWED:", item.clip_export_allowed)
    print("BFS06_FINAL: HUMAN_REFERENCE_AND_RIGHTS_REVIEW_REQUIRED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
