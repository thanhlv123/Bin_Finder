# ZB-01 — Z5-inspired editorial intent experiment

Status: **Research-only**. The new producer is opt-in and is NOT wired into the normal Bin Finder search UI or provider pipeline.

## Evidence and scope

Z5 research suggests separating whole-story context, scene meaning, visual constraints and multiple search queries. F018 currently has a conservative deterministic scene planner; F002 builds mostly lexical searches. ZB-01 independently implements a bounded contract and a local Ollama prototype. No Z5 source, binary code, or prompt wording is copied.

## Files

- src/bin_finder/search/semantic_intents.py: immutable StoryCapsule / SceneSearchIntent, validation, legacy fallback.
- src/bin_finder/search/semantic_planner.py: opt-in LocalEditorialPlanner using explicit loopback-only Ollama /api/chat; no startup or production-discovery invocation.
- tests/test_zb01_semantic_intents.py and tests/test_zb01_local_editorial_planner.py: offline tests for a fake model, invalid responses, URL restrictions and fallback.

No additional dependencies. No production search, F021 verifier, GUI, acquisition, approval, session schema or model installation change.

## Opt-in behavior

An experimental caller explicitly constructs LocalEditorialPlanner() and calls suggest_queries(scene, full_script=..., capsule=...). The result is a query list; it is **not automatically used for a real search**. Constructing the planner does not send a network request.

Defaults: qwen3-vl:4b, http://127.0.0.1:11434, stream=false, format=json, num_ctx=8192, num_predict=4096, temperature=0. A thinking model may fail strict parsing: this will fall back to unchanged F002 queries. The tool does not pull or install models.

A valid StoryCapsule is optional for scripts no longer than 3000 characters. **Longer scripts require a capsule**: without one, the code fails safely without sending any Ollama request. Automatic full-story capsule creation is *not* implemented; silent truncation is avoided.

## Contract and guards

SceneSearchIntent includes exact scene_id and narration_text, visual_goal, required_entities, must_show, must_not_show, 1–3 queries, uncertainty and provenance. Required named entities must appear in the full script and be retained in every query. Invalid/oversized outputs preserve F002 queries. These checks cannot establish semantic truth; an editor and real footage benchmark remain essential.

Only HTTP loopback endpoints allowed; no URLs with embedded credentials, redirects, system proxies, arbitrary response sizes or unlimited timeouts. No change to scene IDs, licenses or selected clips.

## Validation

- Commit f08e4a0: GitHub Actions Windows run 39921563276 PASS (Python 3.12 compile, full pytest, FFmpeg smokes, PyQt6 GUI).
- New optional producer: mock tests passed in a standalone local Python harness; **the latest full GitHub Windows run must be inspected separately**.
- No real Ollama query-generation accuracy test and no provider search benchmark yet.

Windows local test command (on the ZB-01 research branch; not F021):

    $env:PYTHONPATH = "src"
    python -m pytest -q tests/test_zb01_semantic_intents.py tests/test_zb01_local_editorial_planner.py tests/test_query_builder_f002.py tests/test_scene_planning_f018.py

## Integration gates

1. Full Windows CI and F002/F018 regression PASS.
2. Separate real Ollama quality study with labeled scenes, negations, ambiguous entities and NO_MATCH.
3. Compare baseline vs planned queries using identical provider searches and labeled clips: Recall@5, Precision@5, wrong-subject rate, NO_MATCH, latency and VLM cost.
4. Wire behind an explicit opt-in flag only if evidence shows a benefit; preserve legacy fallback and human approval.
5. Do not add GitHub repos unless Z5-first proves insufficient.
