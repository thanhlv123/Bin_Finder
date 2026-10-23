# ZB-01 — Z5-inspired editorial intent experiment

**Status:** Experimental contract ONLY. No production search, GUI, provider, F021 VLM, F022, or model-calling logic is changed.

## Purpose

Bin Finder's F018 scene planning and F002 query builder are conservative and largely lexical. Z5 prompt research suggests a useful separation between whole-story context, a visual goal for each semantic beat, and multiple editorial search angles. This experiment **independently implements only the bounded data contract** for future scene-level plans; it does not copy proprietary Z5 code or prompt text.

## Files

- `src/bin_finder/search/semantic_intents.py`: immutable `StoryCapsule` and `SceneSearchIntent`, bounded validation, a pure opt-in query adapter.
- `tests/test_zb01_semantic_intents.py`: offline tests for valid input, preservation of scene identity, fallback, unsupported named entities, query limits and invalid provenance.

No new runtime dependencies.

## Contract boundaries

An opt-in caller may pass a structured mapping containing:

- `scene_id`, `narration_text`: must exactly correspond to the requested scene.
- `visual_goal`, `must_show`, `must_not_show`, `uncertainty`: editorial metadata for later evaluation; **currently not wired into ranking/VLM**.
- `required_entities`: named terms present in the full script; every proposed query must retain them.
- `queries`: one to three strings, max 160 characters each, no duplicates.
- `provenance`: `script` or `editor_review`.

`proposed_queries_for_scene(scene, proposed, full_script=..., max_queries=...)` returns these queries only when the mapping passes validation. Missing or malformed input returns the original `build_scene_queries` output; the scene object is not modified. No plan is loaded automatically and **there is no GUI toggle yet**.

Important: validation cannot prove factual accuracy of `visual_goal` or `must_show`. This is a contract/safety check, not semantic comprehension or stock-footage retrieval quality. A future planner will need bounded output, grounding tests, explicit opt-in and real-footage comparisons.

## Explicit non-goals

- No modifications to PR #29 or its F021 Ollama verification path.
- No downloads, API calls, AI model pulls, GUI changes, rights-status changes or auto-approval.
- No blending of Storyblocks proprietary code or Z5 prompt wording into Bin Finder.
- No automatic semantic claims derived from the narration yet.

## Acceptance gate before wiring into discovery

1. Run this test file and existing F002/F018 tests on Windows Python 3.12.
2. Review the 12 scenario fixtures in the ZB-01 research pack (they are editorial ground truth, **not measured provider results**).
3. Add separately approved query-planner producer with validated, bounded JSON output and offline deterministic fallback. Do not wire the F021 vision verifier into query planning.
4. Compare **legacy vs planned** queries using the same search providers and labeled footage: Recall@5, Precision@5, wrong-subject rate, NO_MATCH behavior, query latency and VLM cost.
5. Proceed only if metrics support improvement without breaking stable scene IDs, clip duration, licensing, sessions or human approval. Otherwise keep the legacy path. Do not add more GitHub repos unless needed.

## Local validation

```powershell
$env:PYTHONPATH = "src"
python -m pytest -q tests/test_zb01_semantic_intents.py tests/test_query_builder_f002.py tests/test_scene_planning_f018.py
```

The experimental tests passed **11/11 in a standalone Python harness containing the matching Bin Finder scene/query contracts**; this is **not** a full repository CI or Windows result. Full repository/Windows validation is still pending.
