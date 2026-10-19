"""Explicit, bounded live acceptance. Never imported by ordinary test collection."""
import argparse
import tempfile
from pathlib import Path

from bin_finder.acquisition import AcquisitionRequest, AcquisitionService, verified_candidate_path
from bin_finder.evaluation import ReviewDecision
from bin_finder.models import SceneRecord
from bin_finder.provider_config import ProviderConfig
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.service import DiscoveryService, SearchOptions


def run(*, approve_test_download=False):
    keys = ("pexels", "pixabay")
    if not approve_test_download:
        return {key: "SKIPPED_NOT_APPROVED" for key in keys}
    config = ProviderConfig.load()
    registry = ProviderRegistry.from_config(config)
    discovery = DiscoveryService(registry)
    statuses = {}
    # OS temporary storage, outside the repository; cleanup on exit.
    with tempfile.TemporaryDirectory(prefix="bin-finder-f012-") as directory:
        acquisition = AcquisitionService(Path(directory), max_bytes=256 * 1024 * 1024,
                                         timeout=15, deadline=120)
        for key in keys:
            if not getattr(config, key + "_api_key"):
                statuses[key] = "SKIPPED_NO_CREDENTIAL"
                continue
            try:
                batch = discovery.search_scene(SceneRecord("f012-smoke", 1, "ocean"),
                    SearchOptions((key,), limit=1, local_first=False))
                if not batch.candidates:
                    raise ValueError("No candidate")
                candidate = batch.candidates[0]
                # This acceptance-only review is authorized by the explicit flag.
                review = ReviewDecision(candidate.scene_id, candidate.candidate_id, "accepted",
                                        provider=key, source_id=candidate.source_id)
                result = acquisition.acquire(AcquisitionRequest(candidate, review, True))
                if verified_candidate_path(result.candidate) != result.local_path:
                    raise ValueError("Integrity failure")
                hit = acquisition.acquire(AcquisitionRequest(candidate, review, True))
                if not hit.cache_hit:
                    raise ValueError("Cache failure")
                statuses[key] = "PASS (download verified; cache hit verified)"
            except Exception:
                statuses[key] = "FAIL"
    return statuses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-test-download", action="store_true")
    args = parser.parse_args()
    statuses = run(approve_test_download=args.approve_test_download)
    for provider, status in statuses.items():
        print(f"{provider}: {status}")
    return 1 if "FAIL" in statuses.values() else 0


if __name__ == "__main__":
    raise SystemExit(main())
