"""Explicit, bounded live acceptance; never imported by the unit suite."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from bin_finder.models import SceneRecord
from bin_finder.provider_config import ProviderConfig
from bin_finder.providers.base import ProviderError, SearchRequest
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.service import DiscoveryService, SearchOptions


def run(script: Path | None = None) -> dict[str, str]:
    registry = ProviderRegistry.from_config(ProviderConfig.load())
    report = {}
    configured = []
    for key in ("pexels", "pixabay"):
        provider = registry.get(key)
        if not provider.status().configured:
            report[key] = "SKIPPED_NO_CREDENTIAL"
            continue
        configured.append(key)
        try:
            result = provider.search(SearchRequest("smoke", "ocean", limit=3))
            report[key] = "PASS" if result.candidates and all(
                c.source_id and c.source_url for c in result.candidates
            ) else "FAIL"
        except ProviderError:
            report[key] = "FAIL"
    if not configured:
        report["real_script_search"] = "SKIPPED_NO_CREDENTIAL"
    elif script is None:
        report["real_script_search"] = "FAIL"
    else:
        # Same sentence splitting and stable scene IDs as the existing GUI.
        chunks = [part.strip() for part in script.read_text(encoding="utf-8").replace("\n", " ").split(".") if part.strip()]
        scenes = [SceneRecord(f"scene_{i:03d}", i, text + ".") for i, text in enumerate(chunks[:3], 1)]
        service = DiscoveryService(registry)
        results = [service.search_scene(scene, SearchOptions(tuple(configured), limit=3)) for scene in scenes]
        report["real_script_search"] = "PASS" if results and all(r.candidates and not r.notices for r in results) else "FAIL"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit live API checks; at most 8 requests, no media downloads")
    parser.add_argument("--script", type=Path, help="Real UTF-8 script; search the first three scenes")
    args = parser.parse_args()
    try:
        report = run(args.script)
    except (OSError, ValueError):
        print(json.dumps({"real_script_search": "FAIL"}))
        return 1
    print(json.dumps(report, indent=2))
    return int("FAIL" in report.values())


if __name__ == "__main__":
    raise SystemExit(main())
