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
