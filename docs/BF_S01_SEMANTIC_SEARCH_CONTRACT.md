# BF-S01 — Semantic Footage Search Contract (research only)

**Status:** Independent, offline, pure-Python experiment built from `main`. Not wired into Bin Finder's `DiscoveryService`, PyQt6 GUI, Ollama, F021 vision, the ZB-03 review timeline, downloads, or CapCut export. All code and tests were written independently; **none is copied from recovered commercial Z5 source**.

## Objective

Replace the assumption **one narration sentence → lexical search** with a provider-neutral contract:

```
Narration SceneRecord[] (unchanged)
    → narrative Beat[] (partition scenes in order)
    → VisualSlot[] (one or more shots per beat; shots may span scenes)
    → Editorial decision (search / hold / transition / graphic / no_match)
    → Search slot: subject + moment + action, image constraints
    → FUTURE provider search + metadata/vision ranking + human review
```

Search is a *decision*, not a mandatory fallback for every sentence.

## Evidence from Z5 research vs independent design

The Z5-REA-17 static recovery reports `_slot_payload` sending `beat_id`, a slot (`slot_id, role, meaning, source_text, visual_brief, required, text_overlay`), and beat (`narration, meaning, beat_context, must_have, avoid`, optionally `focus, metaphor_note, section_context`) to its local prompt assembly. AI is instructed to decide editorial treatment and generate three query angles: subject, moment, action. The original exact parser/schema and end-to-end behavior are **not** proven by this evidence.

Z5-REA-22/25 found a separately reviewed video candidate flow and a source-priority-based auto selection path with technical download failover, but **did not prove video-frame-based semantic ranking** in that path. The source-priority order is not a scoring rule we should copy. SRC-10 reconstructed a large `Candidate` class statically, but at that checkpoint VideoCandidate/SearchPacket and behavioral golden parity remained unresolved.

BF-S01 intentionally **does not import Z5 or use recovered implementation details**. The contract below adapts *general observed workflow principles* and is independently specified to address known Bin Finder weaknesses.

## Contract v1

Module: `src/bin_finder/search/visual_search_contract.py`.

- `script_digest(scene_records)` creates a deterministic SHA-256 fingerprint for the given scene IDs, order and English/Vietnamese narration. Any new/edited script invalidates an old plan; the hash is **identity control, not a semantic truth guarantee**.
- `parse_semantic_search_plan(plan, scenes)` checks input structure and returns frozen `SemanticSearchPlan` or raises a short fixed `SearchPlanError` code with **no raw narration or credentials in the error**.
- `Beat`: `beat_id`, ordered `scene_ids`, `meaning`, `anchor_text`, `section_context`, `metaphor_note`. Beats partition the existing `SceneRecord` list in order; every original scene appears once and no scene ID changes. Anchors are exact excerpts from narration (not fabricated evidence).
- `VisualSlot`: `slot_id`, `beat_id`, contiguous `scene_ids`, `role`, `action`, `evidence_type`, `entity_policy`, `source_text`, `visual_brief`, `must_show`, `must_not_show`, `required_entities`, `queries`, `reuse_from_slot_id`, `uncertainty`. Source text is an exact excerpt from the slot's mapped narration.
- `action` = `search|hold|transition|graphic|no_match`. Non-search actions **must have zero queries and no stock-search constraints**; `no_match` explicitly explains uncertainty. `hold` must reference the most recent planned search or graphic visual; actual usable media is NOT inferred.
- `search` has three distinct ordered `VisualQuery` angles: `subject`, `moment`, `action`. Each requires a concrete text query and at least one `must_show` item. `evidence_type` = `direct|contextual|symbolic`; `entity_policy` = `strict|contextual|unspecified`. No semantic accuracy is inferred by these labels.
- Each slot is within one beat, can cover multiple adjacent scenes, and several slots can refer to the same narration scene. Every scene is covered by at least one *plan action*, not necessarily a validated/renderable media clip.
- `plan.search_requests()` yields only `SlotSearchRequest` data for `search` slots, never a network call. `plan.unresolved_slot_ids()` labels `transition|graphic|no_match` for later editorial/timing work; `hold` is deliberate continuity but still requires a real selected previous clip.
- Frozen objects, bounded strings/lists and unique IDs defend against malformed LLM data. This **does not** fact-check salary claims or prove rights, dates, people, places or footage authenticity.

## Example — abstract narration must not fabricate stock search

Synthetic narration (not Z5 data):

1. `scene_001`: `Office towers glow after dark.`
2. `scene_002`: `Commuters crowd trains in the evening.`
3. `scene_003`: `City lights cannot prove real wages.`
4. `scene_004`: `Reliable charts need verified wage and price figures.`

Possible editorial outline:
- Beat 1, scenes 001–002, `slot1`: `search` for illuminated office buildings and night commuting context (or *two separate slots* for different subjects).
- Beat 2, scene 003, `slot2`: `transition` with **zero** stock queries; needs later timing resolution.
- Beat 2, scene 004, `slot3`: `graphic` requiring verified numbers, **zero** stock queries. A stock chart is not evidence that its displayed values are true.

The contract can validate this outline; it **cannot** decide whether one combined shot is visually realistic. Semantic evaluation of scene/shot subject separation remains an additional acceptance gate.

## Interface relationship to current Bin Finder

Existing `main`:
- `search/query_builder.py:build_scene_queries(scene)` extracts scene keywords and narration tokens;
- `search/service.py:DiscoveryService.search_scene(scene,options)` sends queries to providers, deduplicates by (`provider`, `source_id`) and assigns metadata-overlap scoring; the current `local_first` option may early stop on metadata score;
- `providers/registry.py` registers YouTube, Storyblocks, Pexels, Pixabay and local library, subject to configuration/access.

**Do not swap BF-S01 into `build_scene_queries` by default.** A future separate BF-S02 adapter must:
1. Associate provider request/response with **slot_id**, not only `scene_id`, avoiding cross-slot overwrite.
2. Send each of the 3 query texts as distinct searches; avoid a mandatory lexical fallback for non-search actions.
3. Preserve the precise query axis, constraints, source/provenance, API status and candidate duplicates until normalized/deduplicated under slot identity.
4. Preserve human-selected and locked media through retries. Distinguish transport failure vs semantic NO_MATCH; do not auto-select lower-quality footage.
5. Treat `local_first` as advisory until verified visual evidence is considered; never assume metadata score is truth.
6. Delegate actual frame checks to a separately approved F021-style vision adapter. No image is uploaded without opt-in; keep loopback only for local VLM.
7. Hand over candidate choices (including unresolved slots) to a human timeline review model before any real video or CapCut export.

Neither BF-S01 nor a structural contract is an estimator of top-3 footage relevance.

## Gates for this research PR

1. Pure-Python unit tests exercise three synthetic genres (travel/history/economy), multi-scene slot, multiple slots per scene, hold, transition, graphic, no_match and stale-script invalidation.
2. Negative tests reject wrong scene anchoring, out-of-order scene/beat identity, contradictory constraints, duplicate slots, wrong axes, invalid query shape, silent fallback or mutated original input.
3. Full Windows CI on draft PR against `main`; no need to change GUI, F021 or other open PRs.
4. **Human quality test still needed**: at least 3 genres and annotated footage availability; test actionable search intents instead of only structural JSON pass. If actual query relevance is not improved, retain branch as design reference; do not merge.

## Local Windows offline verification

After opting to check out the branch in a clean worktree (not required for GitHub CI):

```powershell
$python = 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe'
$env:PYTHONPATH = 'D:\YouTubeTools\Bin_Finder_BFS01_Research\src'
& $python -m pytest -q 'D:\YouTubeTools\Bin_Finder_BFS01_Research\tests\test_bf_s01_visual_search_contract.py'
```

No API keys, private benchmark scripts, model requests, provider calls, or local video files are used by these tests.

## Deferred work

- Controlled opt-in Ollama producer that emits this exact plan schema, with independent human evaluation, no automatic fallback.
- Semantic query anchor and contradiction checking beyond structural shape.
- Provider-neutral candidate envelope, availability-aware intent repair and safe retry (BF-S02).
- Metadata/vision scoring with evidence/no_match decision and top-3/5 human assessment (BF-S03).
- Timeline and CapCut handoff with immutable approved edit spans, source IDs and verified media rights (BF-S04).
