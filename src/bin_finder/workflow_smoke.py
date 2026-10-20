"""Explicitly authorized, bounded F013 live acceptance; never ordinary pytest."""
import argparse
import json
import tempfile
from pathlib import Path

from bin_finder.acquisition import AcquisitionService
from bin_finder.analysis.cache import AnalysisCache
from bin_finder.analysis.service import CandidateAnalysisService
from bin_finder.evaluation import ReviewDecision
from bin_finder.models import SceneRecord
from bin_finder.provider_config import ProviderConfig
from bin_finder.providers.registry import ProviderRegistry
from bin_finder.search.service import DiscoveryService, SearchOptions
from bin_finder.workflow import WorkflowService, WorkflowRequest


def run(*, approve_test_acquisition=False):
    providers = ("pexels", "pixabay")
    if not approve_test_acquisition:
        return {key: "SKIPPED_NOT_APPROVED" for key in providers}
    config = ProviderConfig.load()
    discovery = DiscoveryService(ProviderRegistry.from_config(config))
    statuses = {}
    with tempfile.TemporaryDirectory(prefix="bin-finder-f013-") as directory:
        root = Path(directory)
        for key in providers:
            if not getattr(config, key + "_api_key"):
                statuses[key] = "SKIPPED_NO_CREDENTIAL"
                continue
            try:
                scene = SceneRecord("f013-smoke", 1, "ocean")
                batch = discovery.search_scene(scene,
                    SearchOptions((key,), limit=1, local_first=False))
                candidate = batch.candidates[0]
                # Acceptance-only review, authorized by the explicit command flag.
                review = ReviewDecision(scene.scene_id, candidate.candidate_id, "accepted",
                                        provider=key, source_id=candidate.source_id)
                analysis = CandidateAnalysisService(cache=AnalysisCache(root / key / "analysis.sqlite3"))
                service = WorkflowService(root / key / "run", analysis=analysis,
                    acquisition=AcquisitionService(root / key / "media", max_bytes=256 * 1024 * 1024,
                                                    timeout=15, deadline=120))
                first = service.run(WorkflowRequest((scene,), (candidate,), (review,), True))
                item = first.items[0]
                if item.stage != "analyzed" or item.analysis is None or item.acquisition_reused:
                    raise ValueError()
                cached = analysis.cache.get(item.analysis.fingerprint.sha256,
                    item.analysis.transcript_sha256, item.analysis.analyzer_version)
                if cached is None:
                    raise ValueError()
                # Resume original remote candidate without renewed download authorization.
                second = service.run(WorkflowRequest((scene,), (candidate,), (review,), False))
                resumed = second.items[0]
                if (resumed.stage != "analyzed" or not resumed.acquisition_reused or
                        resumed.analysis.cache_key != item.analysis.cache_key):
                    raise ValueError()
                payload = json.loads(second.state_path.read_text(encoding="utf-8"))
                text = second.state_path.read_text(encoding="utf-8")
                if not payload["items"] or any(secret and secret in text for secret in
                    (config.pexels_api_key, config.pixabay_api_key)) or "Authorization" in text:
                    raise ValueError()
                statuses[key] = "PASS"
            except Exception:
                statuses[key] = "FAIL"
    return statuses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-test-acquisition", action="store_true")
    args = parser.parse_args()
    statuses = run(approve_test_acquisition=args.approve_test_acquisition)
    for provider, status in statuses.items():
        print(f"{provider}: {status}")
    return 1 if "FAIL" in statuses.values() else 0


if __name__ == "__main__":
    raise SystemExit(main())
