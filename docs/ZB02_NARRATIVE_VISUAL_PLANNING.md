# ZB-02 — Narrative Visual Planning (research MVP)

**Status:** Isolated offline contract; NOT connected to Bin Finder production search, ZB-01 local Ollama, GUI, footage providers, acquisition, timeline, or F021. No commercial application code/prompt was copied.

## Problem and decision

ZB-VIDEO-01 editorial study revealed that “one sentence -> one query -> one clip” is too rigid. Documentary narration includes visual nouns/actions, metaphors, factual claims, transitions and pauses. A sentence may need zero, one or several fresh shots; one shot may span multiple narration scenes. High rates of structurally valid model JSON are **not** evidence of useful footage retrieval.

**New design:** script -> narrative blocks -> visual shot sequence -> shot-level search intents -> provider candidates -> editorial/vision verification -> timeline.

- **Narrative blocks** group adjacent narration scenes into a chapter/idea with purpose (establish, develop, contrast, explain, bridge, conclude). They partition the *existing* stable `SceneRecord` IDs in order.
- **Visual shots** specify an editorial **action** independently of any individual narration sentence. The action is one of:
  - `search`: an explicit visual goal, evidence label (`direct`, `contextual`, `symbolic`) and 1–3 independent candidate search queries;
  - `hold`: continue an already planned visual without searching for another video, referencing the most recently planned visual shot;
  - `transition`: the editor needs a narrative visual change, but **no stock search** is mandated;
  - `graphic`: future chart/map/text action, with factual content to be verified before actual rendering; **no stock search**.
- A shot can reference multiple adjacent narration scenes. Conversely, multiple shots can cover the same narration scene. No mandatory one-to-one relation.
- `evidence_type=not_applicable` for non-search actions. `symbolic` is an illustration, not proof. Do not use background pictures to claim evidence of salaries, power-outage duration, export prices, historical timelines, etc.

## Scope implemented now (ZB-02 A)

`src/bin_finder/visual_planning.py` has a dependency-free, immutable model and `parse_visual_story_plan(payload, scenes)` validation boundary:

1. The input narration scene IDs and order come from the existing production `SceneRecord` records; scenes are **not modified**.
2. Narrative blocks must partition all input scenes in their original order, with no duplicates or missing segments.
3. Shots may cover adjacent scene ranges within one block; multiple shots can use the same scene, but shot order cannot run backward.
4. Every narration scene must have **at least one planned action**. A transition is a plan marker, not verified media.
5. `search` requires 1–3 bounded queries; `hold`, `transition` and `graphic` reject stock search queries.
6. `hold` can only reference the most recent visual shot; it is an intentional continuation, **not** a newly selected clip or an anti-source-rotation violation.
7. Untrusted values, lists, IDs and lengths are bounded. No code execution, model request, remote APIs or disk write.
8. `plan.search_requests()` yields a **list of candidate search requests**, not a provider call. Human verification and clip rights still belong downstream.

This first gate verifies **structure and coverage only**, NOT whether an AI's storyboard is semantically truthful or cinematographically effective.

## Minimal schematic (synthetic example)

The narration contains scene IDs `scene_001`, `scene_002`, `scene_003`.

```json
{
  "format": "bin_finder_visual_plan_v1",
  "plan_id": "synthetic_harbor_01",
  "blocks": [
    {
      "block_id": "b1",
      "scene_ids": ["scene_001", "scene_002"],
      "role": "establish",
      "summary": "Fishing harbor and work",
      "visual_purpose": "Introduce physical surroundings"
    },
    {
      "block_id": "b2",
      "scene_ids": ["scene_003"],
      "role": "bridge",
      "summary": "Transition to social conditions",
      "visual_purpose": "Lead into the next narrative chapter"
    }
  ],
  "shots": [
    {
      "shot_id": "s1",
      "block_id": "b1",
      "scene_ids": ["scene_001", "scene_002"],
      "strategy": "search",
      "evidence_type": "contextual",
      "visual_goal": "Fishing boats coming into the harbor",
      "queries": ["fishing boats returning harbor sunrise"],
      "hold_from_shot_id": null
    },
    {
      "shot_id": "s2",
      "block_id": "b2",
      "scene_ids": ["scene_003"],
      "strategy": "hold",
      "evidence_type": "not_applicable",
      "visual_goal": "Continue harbor footage across the verbal transition",
      "queries": [],
      "hold_from_shot_id": "s1"
    }
  ]
}
```

The example makes **one footage discovery request** for **three spoken scenes**, without demanding a literal stock clip for the bridge. It does not assert an actual compatible video exists, nor solve narration timing.

## Crucial design constraints for future phases

- The current F018 `ScenePlanner` produces 3.5–7-second sentence-level scenes; F006/F014 currently have assumptions around one selected clip per scene. **Do not wire ZB-02 into those modules without an explicit compatibility design** for timing, scene-to-shot mapping and approval.
- A visual plan does **not** prescribe final frame timings. A separate scheduler must align voiceover, footage duration, reuse and transitions; cut/source overlap and source-rotation protections remain mandatory.
- Editing actions may span one sentence, multiple sentences or half a sentence. Shot-level search should not inherit automatic scene-level fallback, which could force a nonsensical lexical search for a metaphor.
- Build an honest no-shot/new-search distinction: `hold` and `transition` are positive editorial decisions, not model failure; `graphic` needs factual verification.
- Prior ZB-01 query producer could be reused **later** to draft `search` requests, but is a separate, still-unmerged PR. ZB-02 begins independently from `main`.
- All user-owned scripts and editorial/video references stay local. Only synthetic examples and tests are committed.

## Planned gates (not implemented here)

**ZB-02 B — Visual-director prototype:** opt-in, loopback-only semantic model to propose blocks and visual strategies; compare suggestions with human-prepared three-genre editorial references. Validate contracts and avoid injecting story motif into off-topic shots.

**ZB-02 C — Search candidates:** use current provider interface only for `search` requests and compare actual licensed results against deterministic scene-level baseline; no automated downloading.

**ZB-02 D — Visual continuity:** verify visual shot sequence, durations, editor adjustments, reuse, similarity, license constraints and human approval before modifying any production selection/timeline logic.

Three distinct evaluation genres are required: travel/social documentary, history, and technology/economics. Assess editorial coverage, visual relevance, unnecessary cuts, hallucinated factual claims, source availability, search cost, and human rework. **Do not optimize exclusively for one Cuba example.**

## Local test (Windows PowerShell 5.1)

On a clean checked-out ZB-02 research branch, with repo venv already present:

```powershell
$env:PYTHONPATH = 'D:\YouTubeTools\Bin_Finder_ZB02_Research\src'
& 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe' -m pytest -q 'D:\YouTubeTools\Bin_Finder_ZB02_Research\tests\test_zb02_visual_planning.py'
```

Do not create a new worktree at the above path until a Windows checkout or worktree plan is approved. GitHub Actions on the draft PR can test the code without a local setup.


## ZB-02 B — opt-in AI Visual Director prototype

Implementation:
- `src/bin_finder/visual_director.py`: independently implemented localhost-only Ollama adapter. Uses the preinstalled `qwen3-vl:4b-instruct` for **text** planning; does not alter any F021 model. One explicit call per `propose(...)` invocation, no automatic retries, no source downloading, no provider access, no GUI integration or saved private script.
- Producer accepts only a **small bounded storyboard sample** (1–8 existing ordered `SceneRecord` objects; combined narration <=4,000 characters), with stable `plan_id`. The local Ollama request carries only `scene_id` and its narration, not reference answers or purchased video assets. The system prompt treats narration as untrusted data.
- Model generates a full `bin_finder_visual_plan_v1` draft with story blocks and variable-length shots. `parse_visual_story_plan` validates the result (including required coverage); invalid model output produces **no plan and no fabricated search fallback**. Fixed-code diagnostics include only status, token counts, content length and presence/absence of thinking—no source text or raw model output.
- The bounded pilot allows no more than 2 shots per narration scene. This is a research limit, not a final editorial rule. An opening visual must be a `search` or `graphic` shot; `transition` and `hold` cannot appear before a visual exists.
- `src/bin_finder/visual_director_smoke.py` offers three invented **synthetic** genres, with a separate human-authored offline example for each: `travel`, `history`, `economy`. The offline examples are *illustrative*, not ground truth. They are **never sent** to Ollama. `tests/test_zb02_visual_director.py` uses a fake Ollama transport to verify all three, without network.

### Safe offline examples, no Ollama

On the same existing Python 3.12 environment, from an isolated checked-out ZB-02 source path:

```powershell
$env:PYTHONPATH = 'D:\YouTubeTools\Bin_Finder_ZB02_Research\src'
$python = 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe'
& $python -m bin_finder.visual_director_smoke --genre travel
& $python -m bin_finder.visual_director_smoke --genre history
& $python -m bin_finder.visual_director_smoke --genre economy
```

Without the next flag, the tool **does not construct** the local model adapter and returns explicitly labeled `EDITORIAL_EXAMPLE_ONLY_NO_MODEL`.

### Live local model only after user approval

```powershell
& $python -m bin_finder.visual_director_smoke --genre travel --approve-local-planner
```

The command makes ONE explicit `/api/chat` request to `127.0.0.1:11434`. It prints either `VALID_MODEL_STRUCTURE_NOT_FOOTAGE_ACCURACY` and the full proposed *synthetic* visual plan, or `INVALID_MODEL_PLAN_NO_PROVIDER_REQUESTS` with bounded diagnostics, exit code 2. Do not interpret JSON validity as production footage success. Running all three genres requires three explicit commands/requests.

### Next acceptance gates

1. Windows CI pass with all legacy tests and three-genre fake Ollama fixtures.
2. Only then a controlled **local** three-genre real Ollama trial to inspect actual planning behavior. Qualitative criteria: grouped narrative purpose; meaningful transitions/holds; fewer unnecessary searches; no misleading evidence; reasonable shots/scene flexibility.
3. If real Ollama struggles with a complete multi-block plan, test a bounded *two-stage* analysis (narrative block outline then shot suggestions) before extending context size or altering production.
4. Search integration and visual timeline acceptance remain separate ZB-02C/D proposals. No merge, GUI changes, model download or alteration of F021.


## First real localhost pilot: synthetic travel (user-run Windows)

The user ran `visual_director_smoke --genre travel --approve-local-planner` at commit `5930178` on Windows. Reported Ollama envelope: `done_reason=stop`, `prompt_eval_count=736`, `eval_count=579`, `thinking_present=false`, `reason=valid`. Output comprised **4 narrated scenes, 2 narrative blocks, 4 proposed shots, and 3 search requests**:

- Block b1 (scenes 001-002): harbor establishing sequence. s1 searches for sunrise fishing boats; s2 searches for unloading fish and mending nets.
- Block b2 (scenes 003-004): contrast to community life. s3 is a `transition` with **no search query**, then s4 searches for families at the morning market.
- Queries target concrete filmable subjects; all four scene IDs appear in the visual plan; no legacy scene-level fallback or provider request was made.

**Interpretation:** technical/local-model and structure pass. The scene-003 transition is **not renderable by itself**: no footage is allocated for that narration interval. Later scheduling must ensure a real visual (continue s2, start s4 earlier, or an approved bridging shot) covers any transition-only spoken interval. Structural coverage does not imply frame-by-frame visual coverage. The trial generated one shot action per narrated scene, and it did **not** actually exercise multi-scene `search` or the `hold` strategy; offline tests cover those contracts but the real model has not demonstrated them.

**Not established:** actual stock availability, visual relevance rankings, source licenses, scene-to-shot timing, human editability, or improvement against the old workflow. Test history and economy with the same pinned commit and model before considering a general quality claim. Do not modify production timeline or merge PR #31.


## Three-genre live Visual Director comparison (user-run; pinned 5930178)

At the pinned `qwen3-vl:4b-instruct` model and the 4-scene synthetic scripts:

| Genre | Blocks | Shots | Search | Hold | Transition | Graphic |
|---|---:|---:|---:|---:|---:|---:|
| Travel | 2 | 4 | 3 | 0 | 1 | 0 |
| History | 3 | 4 | 4 | 0 | 0 | 0 |
| Economy | 2 | 4 | 3 | 0 | 1 | 0 |
| **Total** | **7** | **12** | **10** | **0** | **2** | **0** |

All three generated **valid schemas** and Ollama `done_reason=stop`. This shows the local model can organize narration into blocks and detect some bridges. It does **not** show a reduction in unnecessary cuts, actual shot reuse, availability of stock results, or continuity across a real timeline. All three model-produced plans had one shot per narration scene, with no `hold` and no multi-scene search shot. A search count of 10/12 should **not** become a target ratio in isolation; some beats legitimately merit multiple shots.

Manual editorial review of the user's **separate local outputs**:
- **Travel:** scene 003 is a transition-only marker without any assigned visible medium. Future scheduler must decide whether the previous visual holds through that beat or next footage enters early; neither is yet proven renderable.
- **History:** the concept of merchant activity on an ancient bridge is relevant, but a contemporary reenactment cannot independently prove an actual past event. Search footage for trade routes maps might be a useful source asset; the map's dates, geography, and provenance still require verification. No blanket rule against historical stock maps.
- **Economy:** scene 003 is another transition-only beat. Scene 004 requests stock footage of a "chart showing verified salary and price data", marked as `direct`. A video image of a chart does **not** establish that its figures are verified. A fact-checked `graphic` may be preferable, or appropriate stock may be used explicitly as non-evidentiary illustration.

**Actionable next step (now added):** a separate, **read-only Visual Plan Audit**, implemented in `src/bin_finder/visual_plan_audit.py` and printed by `visual_director_smoke`. It counts block/shot/search/hold/transition/graphic actions, multi-scene shots and scenes with overlapping shots. It raises **review flags**, not automatic rejection:
- `transition-only-visual-coverage-unresolved`: a narrated scene has only `transition` actions, hence no allocated searchable, held or graphic visual. This is a scheduling question.
- `graphic-like-content-routed-to-stock-search`: proposed stock footage resembles a chart/graph/infographic. This is **only** a type/format heuristic; such stock might legitimately be reused as illustrative B-roll, so neither the strategy nor its evidence type is silently changed.

The audit is deliberately **genre-neutral**, and tested with travel/history/economy fixtures. It never reads or exports narration text, executes searches, allocates timing, or changes a valid storyboard. Flags merely identify human review opportunities; they do not establish semantic accuracy.

**Next evaluation gate:** First inspect these audit diagnostics on synthetic smoke; then, if useful, compare model suggestions for longer segments and explicit `hold`/multi-scene opportunities. Do **not** increase token/context budgets, alter production scene mapping or merge PR #31 merely to maximize the count of non-search actions.
