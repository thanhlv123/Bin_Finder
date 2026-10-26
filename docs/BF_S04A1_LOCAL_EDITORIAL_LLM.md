# BF-S04A.1 — Local Editorial LLM Pilot (Research Only)

**Stacked base:** `research/bf-s04a-editorial-shot-planner` (Draft PR #37).  
**Branch:** `research/bf-s04a1-local-editorial-llm`.  
**Scope:** explicit single-slot *text planning* through the user's preinstalled local Ollama. No production GUI/main changes, no stock calls, FFmpeg, frame sampling, cloud services, licensed footage acquisition, rights approval or timeline modification.

## Verified starting point

User-local BF-S04A acceptance at commit `682a66a`: **45/45 tests PASS**; offline example of **13 editor-authored shots / seven VisualSlots / 28 seconds**, with 2 archival-person/event, 7 contextual-stock, 2 symbolic and 2 graphic. This demonstrates a valid manual/reference structure **but is not evidence a model can generate equivalent output**. Both text reports and JSON export succeeded on user Windows.

## Implementation

- `search/editorial_local_model.py`: `OllamaLocalEditorialPlanner.propose(base,scenes,approve_local_model_call=False)` on a **validated BF-S01 SemanticSearchPlan**, using the previously created `make_editorial_shot_prompt`. Dry run does no HTTP. Explicit true sends **one maximum** POST to `http://127.0.0.1:11434/api/chat`, `stream=false`, `format=json`, `temperature=0`, `seed=0`, `num_ctx=8192`, `num_predict=4096`. Supported local models only: `qwen3-vl:4b-instruct`, `qwen3-vl:4b`. Config fail-closed, timeout <=600s, bounded response <=256 KiB.
- Reuses F021's strict `validate_loopback_url` and `_NoRedirect`; disables system proxies. No HTTP to remote URLs or credentials. Prompt uses **text only** (not video/frames, no image payload). Does not retry or silently substitute editor-authored fixture.
- The model reply must be a **single strict JSON object** (no markdown fences, duplicate keys, NaN/Inf, malformed/missing body). It passes unchanged to `parse_editorial_shot_plan`. The existing shot contract rejects ungrounded `source_anchor`, non 1–5s shots, wrong slot/beat, missing excluded elements, wrong asset/rights route and forged verified/licensed/timeline fields.
- `LocalEditorialOutcome.status`: `local-model-approval-required`, `local-model-unavailable`, `local-model-reply-oversized`, `local-model-envelope-invalid`, `local-model-shot-plan-rejected`, or `local-shot-plan-proposed-human-review`. Exact one-request policy, `calls_attempted` is not an independently instrumented HTTP request count; `confirmed_http_requests` remains `unknown` once the call is attempted.
- `search/editorial_local_smoke.py`: manual single-shot-**slot** pilot from one of seven editor-authored BF-S01 Gaspard excerpt slots (`--slot 1..7`, default 2). This is **AI-generated shots from a fixed prevalidated VisualSlot**, not automatic full-document semantic beat or VisualSlot extraction. The subset uses a new digest of the single excerpt and validates against it.
- Without `--approve-local-model-call` the CLI prints fixed dry-run fields only, zero model calls, no files. After explicit approval, valid proposals may be saved to a new nonexisting `.json` file with `--output-json C:\...\Desktop\BF_S04A1_AutoShot_Slot2.json`. No overwrite; path validation occurs **before** inference; no arbitrary model text or user file paths in stdout. Saved JSON remains local to user's PC.
- Model planning can fail because of limited Qwen3-VL 4B generation capability, its budget, or contract strictness: on failure report `local-model-shot-plan-rejected` and **reason code**, no model output, no automatic fallback or misleading PASS. When valid, report `local-shot-plan-proposed-human-review`, not publication-ready plan. The model's facts, editorial choices, rights and semantic quality remain unverified.
- The local model's earlier BF-S03B vision success on videos does **not** prove successful text-only structured shot planning, so this stage has a distinct acceptance gate.

## Acceptance sequence

1. Offline tests with synthetic/fake Ollama: `tests/test_bf_s04a1_local_editorial_model.py`; no API calls on CI.
2. Windows CI runs the full project tests plus pinned real FFmpeg/export and GUI regression, never sends user script or video to remote services.
3. User Windows: create independent BF-S04A.1 worktree, verify expected commit and clean working tree, run tests with a new `--basetemp` on D:\, run CLI **without opt-in** to check dry-run and zero calls.
4. **Separate explicit user choice** to run one local text-model call with `--slot 2 --approve-local-model-call` on the Savoie ski context. This is not yet an automatic full 7-slot generator.
5. If validated JSON is produced, compare each model-generated 1–5s shot with the editor-authored BF-S04A fixture. Judge source-anchor grounding, actual vs illustrative imagery, source routing, search queries, must-not-show, emotional coherence and coverage. Keep labels/report separate from prompt.
6. If model output is rejected, identify validator reason code and fix **only** the proven issue. Do not weaken evidence/rights constraints to make a model response appear successful.

## Next milestone (not implemented here)

BF-S04A.2: introduce an authorized **arbitrary user-script input** (non-fixture) with an existing verified BF-S01 SemanticSearchPlan, deterministic bounded slot batching and budget controls. Later BF-S04B/C will add fact provenance/licensing decisions and authorized source routing. Human reviews editorial plans before invoking BF-S02/BF-S03B, and all media remains license-pending until separate approval.

**Current boundary:** model may propose shots, but it neither discovers nor downloads stock footage, cannot certify the actual 2022 event, and does not grant publishing rights. The user-provided French biographical narrative remains unverified script input.


## BF-S04A.1R — user-local failure, targeted response contract correction

**Observed user Windows pilot** at `723d7fa`: local offline tests **29/29 PASS**; dry-run showed **zero Ollama calls**; the user explicitly authorized `RUN` for Gaspard slot 2. Ollama `qwen3-vl:4b-instruct` produced a parseable JSON object, but its top-level `format` was missing or incorrect. The validator rejected it as `invalid-shot-format`, and **no JSON file was written**. This is a real *schema rejection*, not proof of bad story comprehension. Raw response was not logged and cannot be reconstructed; do not guess its shot content.

**Narrow correction without weakening evidence rules:**
- `make_editorial_shot_prompt(..., shots_only=True)` requests precisely `{"shots": [...]}`. The model writes **editorial shot rows only**; the app is authoritative for `format=bin_finder_editorial_shot_plan_v1`, `plan_id=bf_s04a_model_proposal`, `base_plan_id` and `source_digest`. The prompt identifies required source anchors, 1–5s bounds, archive/stock classification, exclusions, bilingual queries and no claimed rights.
- `parse_local_editorial_reply` constructs this deterministic envelope **only when model top-level keys equal exactly `{"shots"}`**. Full previous canonical envelopes remain supported and fully verified for backwards compatibility. **Partial wrappers or extra untrusted project-status fields are never silently repaired**. The same strict `parse_editorial_shot_plan` validates all shot content; missing anchors, contradictory exclusions, misclassified media, misleading event claims, forged provenance/rights and timing >5s still fail closed.
- New offline regression cases explicitly model the observed wrong/missing-format issue, check deterministic trusted envelope, absence of network without approval, one fake loopback request with shot-only reply, no invented shot content, and rejection of forged rights.

**Not claimed:** no second real Ollama result yet; a model may still fail other shot-level fields, or produce weak editorial plans even if structurally valid. No hidden model retries, no weakening of factual/rights approval, no external data calls. User-local follow-up test required on new commit before changing wider pipeline.


## BF-S04A.1R2 — observed `invalid-shot-language`, bounded language compatibility

**User-local acceptance evidence (2026-10-26):** checked out `cecb28a0ff8af35dd94eb9661185bf886d9c298b`, ran **39 focused tests PASS** and zero-call dry-run; explicitly authorized one local `qwen3-vl:4b-instruct` text inference for the same Savoie slot. The result was `local-model-shot-plan-rejected`, `invalid-shot-language`; no JSON file was produced and no media/remote provider touched. This proves only that at least one returned `search_queries[].language` field was not one of the allowed ISO codes. The raw model response is not recorded, so **the exact invalid value is unknown**.

**Scoped correction:**
- Text prompt now explicitly requests an ISO two-letter lowercase code `en`, `fr`, `vi`, `es` or `de` and warns not to use `English`, `French`, uppercase `EN` or locale variants like `en-US`.
- Model-only adapter canonically converts **only explicitly mapped unambiguous labels** such as `English` → `en`, `French`/`français` → `fr`, `German` → `de`, `Spanish` → `es`, `Vietnamese` → `vi`, plus the corresponding case differences in ISO codes. This is not machine translation or content inference. Unknown/missing/malformed or ambiguous language labels are **still rejected** with `invalid-shot-language`.
- Normalization takes place in a deep copy before invoking the **unchanged canonical** BF-S04A validator; the canonical schema itself is not relaxed. The original model response is not overwritten, user script and queries are not translated, and shot-level visual briefs, grounded source anchors, `must_show`/`must_not_show`, factual status, rights and approval are **never repaired**.
- New audited field `BFS04A1_LANGUAGE_LABELS_NORMALIZED` reports how many exact labels were transformed on successful model output; no raw untrusted labels, source text or paths are printed.
- New offline tests cover allowed aliases; malformed locale tags `en-US`, unsupported languages, null/numeric labels, preserving source input, never granting rights, no automatic retry, one fake Ollama request and prompt instructions.

**Acceptance:** Windows CI on final head plus user-local focused tests and one separately authorized re-run. If still `invalid-shot-language`, report this exact limitation; do not broaden mappings or guess a language without data. If a new validation reason appears, fix it only after it is grounded by test evidence.
