# BF-S04A — Editorial Shot Planning (research only)

**Branch:** `research/bf-s04a-editorial-shot-planner`  
**Stacked on:** `research/bf-s03b-local-vision-gate` (Draft PR #36).  
**Main/GUI unaffected.** No downloads, provider calls, frame access, Ollama inference, human decisions or timeline edits.

## Purpose: storyboard decisions BEFORE asset search

The user supplied an excerpt of a French biographical news script about Gaspard Ulliel and example B-roll/editing guidance. The useful workflow is not keyword matching each sentence. Instead, break a *semantic beat* into ordered **1–5 second editorial shots**, distinguish authentic archival evidence from context-only stock, recommend target sources, and only then initiate bounded media discovery and human review.

**Explicit limits:** BF-S04A does **not** fact-check the script, verify people/archives, own any licenses, generate licensed assets or automatically segment arbitrary narration using a running LLM. The checked-in Gaspard fixture is an **editor-authored example** based on short user-supplied quotations; it is not model output or evidence any of its news assertions are true.

## Data model and boundaries

`search/editorial_shot_plan.py` provides:
- `parse_editorial_shot_plan(payload, base: SemanticSearchPlan, scenes: Sequence[SceneRecord])`
- immutable `EditorialShotPlan`, `EditorialShot` and `ShotQuery`, with canonical `to_mapping()` JSON output
- multiple shots for a single BF-S01 VisualSlot (max 8), in original BF-S01 slot order; 1–5 second target per shot, maximum 1,000 shots
- exact `source_anchor` excerpt from the provided narration; strictly matched source digest/plan/scene/beat/slot IDs. Script edits invalidate old output
- visible `must_show`, `must_not_show`, `visual_brief`, `visual_tone`, multi-language `search_queries` and `fallback_policy`
- shot kind `asset_evidence_type`: `authentic_person`, `authentic_event`, `location_context`, `illustrative_stock`, `symbolic`, `graphic`
- source router **decisions only**, no API calls:
  - `authentic_person` / `authentic_event` => `licensed_archive_human_review` (not Pexels masquerading as a historical event)
  - `location_context` / `illustrative_stock` => `contextual_stock_search`
  - `symbolic` => `symbolic_stock_search`
  - `graphic` => `graphic_composition` (no search query)
- `factual_status='unverified'`, `rights_status='pending'`, `timeline_approved=False`, with fixed `evidence_notice` for every shot. Fake `verified`, `approved`, wrong source route or forged notice fails closed. **No automatic approval.**
- original BF-S01 parent `must_not_show` requirements are inherited by every illustrative, symbolic or context stock shot. Nonvisual BF-S01 actions `hold`, `transition`, `no_match` must not generate forced searches.
- archival fallback is restricted to `no_match` or `graphic_with_source`; a generic reenactment cannot be substituted as fact. Contextual B-roll requires an illustration label.

These source routes are **planning hints** for future BF-S04C routing, not functioning archival provider connections. Stock search requests are surfaced by `plan.stock_candidates_to_research()`; integration into BF-S02/BF-S03A and scene timing remains separate, future work.

## Pilot: short French Gaspard news excerpts

`search/editorial_shot_smoke.py` uses **seven** short user-supplied scene excerpts and **seven** BF-S01 slots to form **thirteen** ordered, explicitly editor-authored shots totaling **28 seconds**:

| Sequence | Example shots | Route / truthful editorial treatment |
|---|---|---|
| Introduction and awards | Recognizable actor portrait; actual César ceremony | 2 × licensed archives with separate identity, provenance and rights review |
| Savoie ski background | Landscape 2s; blue-piste marker 2s; calm skier POV 3s | 3 × contextual *illustration*, **NOT** the historical collision |
| Death/age line | Brief age text/black-screen treatment | 1 × graphic; facts require independent source |
| Fashion household | Clothing sketch; fabric close-up | 2 × stock illustrations; not genuine family home videos |
| Doberman childhood story | Generic dog detail; symbolic silhouette | 1 × illustration, 1 × symbol; **no invented footage of child injury** |
| Childhood music | Jazz atmosphere; saxophone hands | 1 × symbolic, 1 × illustrative |
| First agency opportunity | Age transition graphic | 1 × graphic; pending validation |

**Result route counts:** 2 archival, 7 contextual stock, 2 symbolic stock, 2 graphic. Sample English/French queries are included in canonical JSON. The fixture is deliberately **not** evidence of historical accuracy: birth, award, accident details, family history and injury require independent reliable sources. Any licensed film/press clips require rights checking; 1–5-second cuts are **not** automatic copyright permission.

## Preparing eventual local model proposals

`search/editorial_shot_prompt.py` provides a bounded **prompt builder only**:
`make_editorial_shot_prompt(base, scenes)`.

It includes slot/scene context and enforces reporting, query, timing and archive-authenticity expectations. User script is treated as untrusted data; any LLM output MUST pass `parse_editorial_shot_plan`. It does **not** contact Ollama or cloud services. The next milestone should add **separate explicit opt-in** for local Ollama text planning, constrained response parsing and quality evaluation against an editor-reviewed gold label. Avoid treating structurally valid plans as narratively correct.

## Smoke + tests

Run offline:

```powershell
$env:PYTHONPATH = 'D:\YouTubeTools\Bin_Finder_BFS04A_Research\src'
& 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe' -m bin_finder.search.editorial_shot_smoke
& 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe' -m bin_finder.search.editorial_shot_smoke --json
```

`tests/test_bf_s04a_editorial_shot_plan.py`: source/slot grounding, 1–5s durations, multi-shot continuity, bilingual queries, archival routing, rejected forged provenance/rights/timeline approval, malformed negative cases, inherited prohibitions, no-match semantics, content immutability, untrusted prompt constraints, and offline smoke.

Windows CI `bf-s04a-research-windows.yml` runs **full project pytest**, pinned real FFmpeg export tests and GUI smoke without any cloud image/footage upload or user credentials.

## Next independent milestones

1. **BF-S04A.1:** local text-model proposal generation with separately granted permission, output validation and editorial comparison, never automatic footage approval.
2. **BF-S04B:** improved evidence taxonomy, fact-source references and user labels (archive licensing / contextual illustration).
3. **BF-S04C:** route approved search requests to provider adapters or manual archive research, without forcing an API result for unresolvable archive content.
4. **BF-S04D:** clip-localization and temporal evidence verification (beyond 3 sparse stills).
5. **BF-S04E:** only after human asset/rights approval, export read-only shot handoff to AI_Video_Editor.

No production GUI, FFmpeg, Ollama, provider API, CapCut or timeline edits in BF-S04A.
