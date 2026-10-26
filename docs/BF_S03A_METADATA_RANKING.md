# BF-S03A — Explainable Metadata Ranking (Research Only)

**Branch:** `research/bf-s03a-metadata-ranking`  
**Stacked base:** `research/bf-s02-slot-candidate-search` (BF-S02.1)  
**Not production:** no changes to Bin Finder production GUI, existing provider API adapters, licensed downloading, F021 verifier, timeline or CapCut.

## Motivation and observed evidence

The user's Windows local BF-S02.1 live pilot successfully queried Pexels and Pixabay (3 queries per source; 6/6 OK). Pexels returned 14 unique candidates and retained 10 (4 cap trimmed); Pixabay returned 12 unique candidates and retained 10 (2 cap trimmed). Balanced subject/moment/action coverage succeeded on the local test (22/22) and Windows CI (632 tests).

**But candidate metadata reveals the next problem:** the desired slot says “At dawn fishing boats enter the coastal harbor”; provider search titles include boats **docked** at a harbor, a **sailing** boat in open sea, and an unrelated **industrial oil refinery at blue hour**. The return axis alone does not verify subject/action/time. A ranking mechanism must prioritize evidence while clearly abstaining from visual truth claims. Provider keyword overlap is not license approval.

## Contract and behavior

`search/slot_metadata_rank.py` exposes:
- `SlotMetadataRanker.rank(validated_plan, slot_search_result) -> MetadataRankResult`.
- Immutable `RankedSlotCandidate` items preserve the original `CandidateHit` identity and all query provenance, with a heuristic score 0–100, fixed evidence fields, fixed explanation codes and an explicit `metadata-only-unverified` status.
- `MetadataRankResult.top_for_review(limit=5)` **only recommends a manual inspection order**; no automatic selection, approval, media access, rights clearance, model inference or temporal motion verification.
- Input is the **capped** BF-S02.1 review pool (20 in the user two-provider pilot). The six BF-S02.1 items trimmed by its cap cannot be recovered by S03A without increasing the upstream cap. This is intentional phase separation, not a claim of ranking all 26 original candidates.

### Score (research heuristic, not trained or validated accuracy)

Signals are matched against provider title and description **only**, never signed URLs, `source_metadata`, API-provided scores, licensing status, provider name, or the number of query axes returning an asset. Text is tokenized and lightly normalized; lexical coverage does **not** prove what is in the video.

| Signal | Max contribution | Meaning |
|---|---:|---|
| Subject query terms | 38 | Coverage of proposed subject words |
| Action query terms | 20 | Coverage of action keywords |
| Moment query terms | 12 | Coverage of time/context keywords |
| `must_show` terms | 20 | Non-exclusive lexical support; visual presence unverified |
| Resolution/orientation | 10 | Preferred landscape (≥1280 × 720); missing metadata gets zero bonus |
| Required entities missing from metadata | up to −12 | Uncertainty, not proof that the location/entity is absent |
| `must_not_show` phrase in provider text | −32 | Warning based on an explicit metadata phrase |
| Motion required; text indicates only stationary state | −24 | Flag “docked/moored/anchored” when narration asks for entry/movement, unless movement is also indicated |

Only known explanation-code strings are emitted; title/description never appear in the reason list. `metadata-promising-for-review` is **not** “verified” and does not override an explicit conflict. `metadata-caution` flags conflicts and can remain visible to a human as an editorial or contextual alternative. `metadata-limited-evidence` means the listing does not strongly support the specified slot.

A provider's rights label remains data, not permission to download/export. `query.matched_axes` is provenance, **not** a reliability or relevance multiplier. Deterministic ordering uses score descending, then original first-seen order/provider/ID. Metadata-only scores must **not** be compared with calibrated probabilities.

### Known limitations

- Lexical normalization is deliberately small and misses synonyms/paraphrases (e.g., “arriving” vs “approaching”), multilingual idioms and non-literal narration.
- Provider titles, keywords and descriptions can be wrong or incomplete.
- The stationary/motion conflict rule is a cautious cue, not a complete activity recognition system. A video with a docked boat in its title could also depict a boat entering; actual frames are needed to decide.
- 16:9 preference is not a crop/license/asset eligibility gate. Missing resolution/duration is unknown, not a hard failure.
- If exact locations and dates are not mentioned in metadata, `required_entities` is *uncertain*, not contradicted. Historical facts always need external evidence and human review.
- There is no hard `no_match` conclusion from metadata alone. BF-S01 explicit `no_match`/hold/graphic/transition slots are not passed to metadata search/ranking.
- **No evidence yet of higher semantic-match accuracy** than BF-S02.1 or old Bin Finder. Human-labeled evaluation and BF-S03B visual verification are required.

## Offline acceptance tests

`tests/test_bf_s03a_metadata_rank.py` covers three independent story genres, with entirely synthetic/no-network records:
1. Travel: sailing fishing boat > docked fishing boat > industrial refinery metadata for “fishing boats enter harbor at dawn.”
2. History: Havana 1950s classic colonial-street cars > unrelated modern highway footage, with `required_entities` and `must_not_show`.
3. Economics: empty supermarket shelves amid food shortages > explicitly fully stocked shelves.

Additional tests: provenance axes do not artificially inflate scores; provider scores/license labels are neutral; preferred landscape resolution is only a bonus; unknown resolution is not automatic rejection; no subject evidence is not “promising”; signed URLs in records do not enter explanations; empty slots, duplicates, bad provenance, stable ties, and strict result bounds.

`tests/test_bf_s03a_metadata_smoke.py` covers offline default (0 provider calls), explicit dual-flag provider approval, six exactly bounded fake provider requests, no signed URLs/keys in reports and source ID allowlisting.

**No cloud VLM, API traffic, private frames or downloads in CI.**

## Research CLI usage

Offline, no secrets/config, no provider calls:

```powershell
& 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe' -m bin_finder.search.slot_metadata_smoke
```

Live requires **both** switches; searches one synthetic harbor visual slot, using exactly three bounded search queries per provider (six total) and ranks the **shared cross-provider review pool**, without creating thumbnails/video downloads:

```powershell
& 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe' -m bin_finder.search.slot_metadata_smoke --project-root 'D:\YouTubeTools\Bin_Finder\Bin_Finder' --live-providers --approve-provider-calls
```

Set `PYTHONPATH` to this isolated research branch `src` before running; ensure the existing local private `config/providers.local.json` is used and stale process API-key variables are temporarily unset (restore them afterward). The CLI prints candidate source IDs, bounded heuristic scores, fixed reasons, and the top-five manual-review order; **never raw HTTP URLs, API keys, metadata descriptions, raw exceptions, or candidate download links**.

## Acceptance / next milestone

1. GitHub Windows CI full regression and FFmpeg+GUI smoke green.
2. User Windows offline 3-genre and CLI tests run with a fresh pytest `--basetemp` on drive D (avoids their inaccessible C:\\Users\\pc\\AppData\\Local\\Temp\\pytest-of-pc).
3. User manually authorizes **at most six** live Pexels/Pixabay metadata-only requests and sends redacted console summary.
4. Compare metadata ranking of “docked” vs “sailing” footage and remove clearly wrong category from top candidates **without claiming frame verification**.
5. BF-S03B will inspect locally accessible permitted video frames via Ollama loopback and allow abstention/manual review; it must **never silently select/download/approve** a candidate.
