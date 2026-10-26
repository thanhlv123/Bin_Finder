"""BF-S04A.2 CLI: offline review of a user-selected BF-S04A.1 JSON plan.

No Ollama requests or API calls. Never rewrite model plan, download footage,
verify claims, change timeline, or inspect video. Only safe fixed label output.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from bin_finder.search.editorial_local_model import (
    MAX_RESPONSE_BYTES, parse_local_editorial_reply,
)
from bin_finder.search.editorial_local_smoke import selected_excerpt
from bin_finder.search.editorial_quality_gate import (
    review_editorial_quality, savoie_editorial_reference,
)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="BF-S04A.2 offline editorial quality review")
    p.add_argument("--plan-json", required=True, help="Absolute path to validated local plan JSON")
    args = p.parse_args(argv)

    print("BFS04A2_MODE: OFFLINE_HUMAN_REFERENCE_QUALITY_REVIEW")
    print("BFS04A2_PROVIDER_CALLS: 0")
    print("BFS04A2_OLLAMA_CALLS: 0")
    print("BFS04A2_CLOUD_UPLOADS: 0")
    print("BFS04A2_MEDIA_DOWNLOADS: 0")
    print("BFS04A2_TIMELINE_CHANGED: False")

    target = Path(args.plan_json)
    if (not target.is_absolute() or target.suffix.casefold() != ".json"
            or target.is_symlink() or not target.is_file()):
        print("BFS04A2_STATUS: invalid-local-file")
        return 2
    try:
        if target.stat().st_size > MAX_RESPONSE_BYTES:
            print("BFS04A2_STATUS: oversized-local-plan")
            return 2
        raw = target.read_text(encoding="utf-8")
        scenes, base = selected_excerpt(2)
        plan = parse_local_editorial_reply(raw, base, scenes)
        report = review_editorial_quality(plan, savoie_editorial_reference())
    except (OSError, ValueError, UnicodeError):
        print("BFS04A2_STATUS: invalid-or-mismatched-plan")
        return 2

    print("BFS04A2_STATUS:", report.status)
    print("BFS04A2_SCORING:", report.evidence_level)
    print("BFS04A2_SHOTS:", report.shot_count)
    print("BFS04A2_REQUIREMENTS_TOTAL:", len(
        report.covered) + len(report.missing))
    print("BFS04A2_COVERED:", ",".join(report.covered) or "none")
    print("BFS04A2_MISSING:", ",".join(report.missing) or "none")
    print("BFS04A2_FLAGS:", ",".join(report.flags) or "none")
    print("BFS04A2_HUMAN_EDITORIAL_REVIEW: True")
    print("BFS04A2_FOOTAGE_VERIFIED: False")
    print("BFS04A2_RIGHTS_APPROVED: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
