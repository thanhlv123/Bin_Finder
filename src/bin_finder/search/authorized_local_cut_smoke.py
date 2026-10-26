"""BF-S06 manual opt-in local cut from separately licensed media.

Supports bounded 1–7s MP4 or one JPEG still with proposed timeline hold.
No YouTube audiovisual fetch. The source is a local media master supplied
independently with user-confirmed usage permission.
"""
from __future__ import annotations

import argparse

from bin_finder.search.authorized_local_cut import (
    AuthorizedCutRequest, AuthorizedLocalCutError, export_authorized_local_cut,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="BF-S06 independent local master 1-7s export")
    parser.add_argument("--source-path", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output-path", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--duration", type=float, required=True,
                        help="1..7 seconds; still mode uses this as timeline hold only")
    parser.add_argument("--mode", choices=("clip", "still"), default="clip")
    parser.add_argument("--provenance", choices=(
        "user_owned_original_master", "licensed_independent_master_copy"
    ), required=True)
    parser.add_argument("--confirm-usage-rights", action="store_true")
    parser.add_argument("--approve-local-cut", action="store_true")
    args = parser.parse_args(argv)

    print("BFS06_CUT_SOURCE: INDEPENDENT_LOCAL_FILE_ONLY")
    print("BFS06_YOUTUBE_API_CALLS: 0")
    print("BFS06_YOUTUBE_AUDIOVISUAL_DOWNLOADS: 0")
    print("BFS06_CLOUD_UPLOADS: 0")
    print("BFS06_RIGHTS_VERIFIED_BY_TOOL: False")

    request = AuthorizedCutRequest(
        source_path=args.source_path,
        source_root=args.source_root,
        output_path=args.output_path,
        output_root=args.output_root,
        start_seconds=args.start,
        duration_seconds=args.duration,
        mode=args.mode,
        provenance=args.provenance,
        confirm_usage_rights=args.confirm_usage_rights,
        approve_local_cut=args.approve_local_cut,
    )
    try:
        result = export_authorized_local_cut(request)
    except (AuthorizedLocalCutError, OSError):
        print("BFS06_CUT_STATUS: invalid-cut-request")
        print("BFS06_CUT_WRITTEN: False")
        return 2

    print("BFS06_CUT_STATUS:", result.status)
    print("BFS06_CUT_DURATION:", result.duration_seconds)
    print("BFS06_CUT_MODE:", args.mode)
    print("BFS06_CUT_WRITTEN:", result.output_written)
    print("BFS06_HUMAN_EDITORIAL_REVIEW_REQUIRED: True")
    return 0 if result.status in {
        "cut-approval-required", "local-clip-created-pending-editorial-review"
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
