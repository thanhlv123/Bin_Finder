# ZB-VIDEO-01 — Private Cuba script-to-footage reference evaluation

Status: **research only**. This is a query-comparison harness, not footage retrieval quality certification.

## Why this exists

The user supplied a 91.52-second YouTube screen recording and a script passage. A preliminary editorial reference describes 15 semantic beats spanning approximately 15.14–88.84 seconds, each with observed imagery, reference search terms and a match category (direct, contextual, editorial metaphor, weak/indirect). These timings are screen-recording timestamps **not** original source-footage timestamps.

The reference movie contains moving/burned subtitles and completed editorial cuts. It is **not suitable for claiming vision-based match precision** without masking subtitles and independently labeled licensed stock candidates. The reference annotations are not independently verified ground truth; they should be reviewed before use for numerical accuracy reporting.

## Copyright and privacy

The source video, still images, scene annotations and user-provided script **are NOT committed** to the public repository. The CLI deliberately loads the user's JSON file **only from a local path**, and never contacts remote services. For opt-in generation, only the beat excerpts / reconstructed narration text are sent to **loopback Ollama**. Expected editorial queries, human annotations and observed visual labels are *not* sent to the model, preventing leakage during query generation.

The user can retrieve the separate reference JSON/ZIP from the ChatGPT research conversation and keep it outside Git.

## CLI mode A: offline baseline (NO Ollama calls)

From the detached ZB-01 worktree, with Python 3.12 and the user-supplied reference JSON saved locally:

    $env:PYTHONPATH = 'D:\YouTubeTools\Bin_Finder_ZB01_Research\src'
    & 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe' -m bin_finder.search.reference_eval --reference 'D:\path\to\cuba_script_footage_benchmark.json' --start 1 --count 15

Outputs one JSON line per beat: baseline F002/F018 context-based query, reference-editor queries, preliminary visual hints and beat category. Prints an explicit note that no real footage retrieval has been measured.

## CLI mode B: explicitly approved local Ollama query generation

Only after confirming that the locally installed model `qwen3-vl:4b-instruct` is available:

    $env:PYTHONPATH = 'D:\YouTubeTools\Bin_Finder_ZB01_Research\src'
    & 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe' -m bin_finder.search.reference_eval --reference 'D:\path\to\cuba_script_footage_benchmark.json' --start 2 --count 1 --approve-local-planner

Each selected beat makes up to **one explicit localhost text-only request**. Default is a single beat, not all 15. Use `--start 12 --count 1` for car-repair actions, and `--start 14 --count 1` for a deliberately weak visual reference. On malformed/no output the code reports a redacted error and falls back to legacy queries; no raw model thinking is logged.

### Acceptance hierarchy

1. Offline fixture validation and Windows pytest/FFmpeg/GUI regressions.
2. Live *structural* Ollama output and manually assessed editorial query relevance for CUBA-02, CUBA-12, CUBA-14, then all 15 beats.
3. Build a separately licensed/local candidate-footage set with independent human labels. Only then measure Precision@5/Recall@5, wrong-subject rate, temporal localization and latency.
4. Compare Z5-inspired vs legacy search on the **same provider results and candidate set**. Merge new behavior only with demonstrated benefit and user approval.

The reference CSV/JSON intentionally includes low-strength matches and examples of footage that **cannot prove** salary figures, long-lasting outages, mileage or decades of repairs. Do not reward a model for inventing evidence.

## Non-goals

No GUI changes, no source downloads, no YouTube crawling, no new providers, no modifications to F021 PR #29, no new dependencies, and no merge to main.


## ZB-01 scene-first revision (research only)

The local Ollama prompt now makes the current narration beat authoritative; previous story context can clarify pronouns/references but must not introduce unrelated earlier motifs. New-style outputs include:
- `scene_anchor`: an exact quoted phrase from the **current beat's narration_text**, preferably naming subject and action;
- `evidence_type`: `direct | contextual | editorial_metaphor | weak_indirect | no_match`;
- `queries`: 1–3 grounded queries, or an **empty** list only for a valid, reasoned `no_match`;
- `uncertainty`: explains why an illustrative scene does not establish an economic/statistical claim.

The validator checks verbatim scene anchoring and a **minimal lexical** overlap from the chosen scene anchor across proposed searches. This detects obvious topic drift, not semantic correctness. Plausible synonyms may be rejected and trigger unchanged F002 fallback. A valid `no_match` results in `planner_queries=[]`, `planner_no_match=true` and `used_legacy_fallback=false`; it must not be confused with invalid output fallback. The research CLI now reports `model_evidence_type` and `model_scene_anchor`.

Existing editor plans without `evidence_type` remain supported for regression compatibility; only new-style proposals enforce the stronger contract. The model prompt requests the new style by default. **No behavior is wired into production.**

### Three-beat local rerun before testing all 15

On a clean, updated isolated research worktree, with private reference JSON available locally and the Instruct tag already installed:

```powershell
$env:PYTHONPATH = 'D:\YouTubeTools\Bin_Finder_ZB01_Research\src'
$python = 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe'
$json = Join-Path $HOME 'Downloads\cuba_script_footage_benchmark.json'
foreach ($index in @(2,12,14)) {
    & $python -m bin_finder.search.reference_eval --reference $json --start $index --count 1 --approve-local-planner
    if ($LASTEXITCODE -ne 0) { throw "Failed to evaluate scene $index" }
}
```

Do **not** evaluate all 15 until the three local results are manually assessed for topic relevance, evidence truthfulness and invalid/NO_MATCH/fallback disposition. The runner never requests reference expected queries or image annotations from Ollama. No real stock footage has been searched or scored.


## Three-beat local result: 6d0efac fallback regression and targeted fix

The real Instruct rerun on the user's Windows machine returned valid Ollama envelopes but rejected **all three** candidates: CUBA-02 and CUBA-14 with `invalid-intent:required-entity-lost`; CUBA-12 with `invalid-intent:scene-anchor-not-in-narration`. This is not evidence of model generation failure or stock search relevance.

Subsequent isolated revisions:
- Compare entity names as **whole normalized tokens**, with controlled singular/plural and Cuba/Cuban alternatives; maintain the rule that truly mandatory entities occur in each query, and reject invented entities.
- Validate `scene_anchor` as an **ordered subsequence of meaningful words** in the current narration (allows dropped grammatical filler words but not injecting unrelated context). Require two distinct cues for nontrivial narration, and still check topic overlap before accepting queries.
- Clarify the prompt that `required_entities` contains **only necessary script-grounded proper nouns** actually carried in every query; generic products/cars belong in the visual constraints.
- Add synthetic tests proving CUBA-14's earlier vintage-car motif is still rejected; CUBA-12's "machines repaired patched" anchor can pass; entity variants must be retained within every search.

The local three-beat Ollama rerun is still required after Windows CI, because structurally valid JSON and synthetic tests are not proof of semantic relevance. No automatic retry, online search, GUI change, F021 change, or merge to main.


## V2 evaluation: isolate the CUBA-12 rejection

The second local three-scene evaluation (commit `f2e3ffb`) completed with:
- CUBA-02: `valid`, `direct`, vintage Chevrolet / colonial architecture query.
- CUBA-12: `invalid-intent:insufficient-scene-focus` and legacy fallback; **the rejected model query was not recorded**, so semantic quality cannot yet be judged.
- CUBA-14: `valid`, `weak_indirect`, Cuban goods in international markets. This stopped the vintage-car context drift, but visuals/price labels alone cannot validate export-price claims.

**Do not relax the scene-focus validator without seeing the actual rejected CUBA-12 search.** A bounded opt-in inspector was added to `reference_eval`:

```powershell
$env:PYTHONPATH = 'D:\YouTubeTools\Bin_Finder_ZB01_Research\src'
$python = 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe'
$json = Join-Path $HOME 'Downloads\cuba_script_footage_benchmark.json'
& $python -m bin_finder.search.reference_eval --reference $json --start 12 --count 1 --approve-local-planner --inspect-rejected
```

`--inspect-rejected` is rejected unless the user *also* explicitly approves a local Ollama request. By default failed candidates remain redacted. The additional `planner_diagnostics.rejected_plan_preview` includes only bounded model-generated `scene_anchor`, `queries`, `required_entities`, `evidence_type`, `visual_goal`, `uncertainty` and `must_show`, if those fields were sufficiently small and well typed. It **never** includes raw Ollama output, the source narration field, complete story, provider credentials or hidden model thinking. Printed debug output stays local unless the user independently chooses to share it.

The accepted CUBA-14 query must still be manually judged as illustrative, not as a claim that a stock shot can prove export prices. No provider lookup, visual evidence, or retrieval effectiveness has yet been measured.


## 15-beat local V3 results and observational-quality gap

User-held private benchmark results from Windows localhost Instruct (no stock provider):
- **11/15 validated plans** (73.3%), **4/15 legacy fallback** (26.7%), **0 valid no_match**.
- Fallback IDs: 05 (`missing-queries`), 09/10 (`query-lost-scene-focus`), 15 (`invalid-list`).
- Review flags on structurally valid plans: unobservable audio or emotion, incorrect `direct` evidence on a metaphor, searching unrelated visual concepts in the **same shot**, gratuitous negative filters, and assertions about outage duration/export prices not visually provable.
- Particularly solid subject/action identification: vintage car and repairs, with remaining action-level shot selection improvements needed.

The changes below are **prompt/harness research**, NOT a claimed footage-accuracy improvement:
- Ask for visible performers/instruments instead of sound seen through a window, visible streets instead of nostalgia as proof, and avoid visually "proving" exact outages/prices/wages.
- Split independent subjects in a compound narration beat across separate queries instead of demanding they appear in the same frame.
- Allow a place-identification beat to request a contextual establishing shot; encourage explicit `no_match` for an abstract bridge without a reliable visual.
- Enforce empty `must_not_show` for no_match and keep the existing per-scene grounding guard (do not loosen to silence fallback).
- When the user explicitly opts into `--inspect-rejected`, include `planner_diagnostics.rejected_plan_preview.field_shapes` to reveal **only** the JSON type and bounded array length for `queries/required_entities/must_show/must_not_show`. No failed model raw payload, story text or thinking.

**New live evaluation required:** rerun representative scenes 03, 05, 07, 09, 10, 13 and 15, alongside the known risk scene 14, using exactly the same private local JSON. Judge visual observability and editorial evidence, not merely `valid`. Do not integrate into production or start footage acquisition unless quality evidence supports it.
