"""Brief-driven metadata discovery with per-run query caching."""
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json
import re

from bin_finder.brief import BriefPlan
from bin_finder.providers.base import ProviderError, SearchRequest
from .credits import license_for


@dataclass(frozen=True)
class FootagePlan:
    version: str
    brief_sha256: str
    script_sha256: str
    sources_used: list[str]
    cues: list[dict]
    candidates_per_source: dict[str, int]

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


def _matches(candidate, config):
    match = re.fullmatch(r"(\d+)x(\d+)", candidate.resolution)
    # Unknown dimensions (including YouTube HD) remain discovery candidates.
    if not match:
        return True
    width, height = map(int, match.groups())
    if width < config.min_width or height < config.min_height:
        return False
    return (config.orientation == "any" or
            config.orientation == "landscape" and width > height or
            config.orientation == "portrait" and height > width or
            config.orientation == "square" and width == height)


def search_footage(plan: BriefPlan, registry, config):
    cache, cues, used, counts = {}, [], [], {}
    briefs = {b.cue_id: b for b in plan.briefs}
    for cue in plan.cues:
        row = {"cue_id": cue.cue_id, "text": cue.text, "candidates": [], "errors": []}
        seen = set()
        brief = briefs.get(cue.cue_id)
        queries = brief.queries if brief else {}
        fallback = next((q for q in queries.values() if q), [])
        for source in config.enabled_sources():
            provider = registry.get(source)
            if provider is None or not provider.status().configured:
                continue
            for query in queries.get(source) or fallback:
                key = (source, query)
                if key not in cache:
                    if source not in used:
                        used.append(source)
                    try:
                        cache[key] = provider.search(SearchRequest(
                            cue.cue_id, query, config.per_query_limit, config.orientation,
                            config.min_width, config.min_height))
                    except ProviderError:
                        # ProviderError text is external to this boundary: do not persist credentials in it.
                        cache[key] = None
                result = cache[key]
                if result is None:
                    row["errors"].append({"source": source, "query": query, "error": "Provider search failed"})
                    continue
                if result.notice:
                    row["errors"].append({"source": source, "query": query, "error": "Provider returned a notice"})
                for original in result.candidates:
                    if original.source_id in seen or len(row["candidates"]) >= config.max_candidates_per_cue:
                        continue
                    candidate = replace(original, scene_id=cue.cue_id,
                                        candidate_id=f"{cue.cue_id}:{original.source_id}")
                    info = license_for(candidate)
                    if (config.exclude_unusable and not info.usable_in_video and source != "youtube") or not _matches(candidate, config):
                        continue
                    seen.add(candidate.source_id)
                    row["candidates"].append({**asdict(candidate), "license": asdict(info),
                                               "reference_only": source == "youtube"})
                    counts[source] = counts.get(source, 0) + 1
        cues.append(row)
    digest = sha256(json.dumps(plan.to_dict(), sort_keys=True, ensure_ascii=False,
                               separators=(",", ":")).encode("utf-8")).hexdigest()
    return FootagePlan("footage_plan_v1", digest, plan.script_sha256, used, cues, counts)
