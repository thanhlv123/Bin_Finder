# BF-S02 — Visual Slot Candidate Search (research-only)

**Branch:** `research/bf-s02-slot-candidate-search`, **stacked on BF-S01** `research/bf-s01-visual-search-contract`. This is an independent implementation inspired by Z5 workflow *principles* established by the user's static analysis, NOT a port of Z5 proprietary binaries or reconstructed source.

## Goal and scope

Consume a **validated** BF-S01 `SemanticSearchPlan` to retrieve provider candidates per visual slot, while preserving the human's review choices. The contract separates **subject**, **moment** and **action** queries. `hold`, `transition`, `graphic` and `no_match` do **not** create a provider request.

```
Validated BF-S01 SemanticSearchPlan
  ├─ search slot-1 ─ subject/moment/action ─ providers ─ candidate pool slot-1
  ├─ transition slot-2 ─ no provider call ─ editorial review marker
  └─ search slot-3 ─ subject/moment/action ─ providers ─ candidate pool slot-3
         ↓
  CandidateReviewPool (immutable; manual choices and locks are protected)
         ↓
  Future BF-S03 metadata/vision reranking
         ↓
  Future BF-S04 Human Review Timeline
```

**Implemented research modules**

- `src/bin_finder/search/slot_candidates.py`: `SlotCandidateSearch.search(plan, scenes, options, approve_provider_calls=True)` uses the preexisting `ProviderRegistry` and `providers.base.SearchRequest` without changing any provider or legacy `DiscoveryService.search_scene`. **Without explicit approval it refuses all provider calls.** It verifies the BF-S01 plan against unchanged narration before making calls.
- Each of the three query axes is submitted independently to every requested configured provider (one search per axis/provider/slot). A bounded budget of up to **18 planned calls** per invocation prevents unintentional broad searches. No retries, downloads, background tasks or video decoding occur. A failed source/query is recorded with a bounded status; other axes/providers can still yield candidates.
- `CandidateHit` stores `slot_id`, `beat_id`, all mapped `scene_ids`, provider-origin `CandidateRecord`, matched query axes and deterministic first-seen order. Dedupe uses `(provider, source_id)` **within the same slot only**. Identical media from different slots remains independently reviewable. Native provider `CandidateRecord.scene_id` stays the initial scene ID because the existing provider API is scene-based; the outer wrapper carries authoritative slot identity.
- `SearchAttempt` statuses are only `ok/empty/provider-error/not-configured/invalid-provider-status/invalid-provider-result`, and never embed raw exception text or credentials. Provider title/metadata and `rights_status` remain **unverified and not a license approval**.
- `src/bin_finder/search/slot_review_pool.py`: immutable `CandidateReviewPool` keeps *all* original slot actions (including editorial-only actions) and their new candidates. **There is no automatic winner.** A human explicitly calls `choose`, `mark_reviewed` (layout-only), then optional `set_lock`. Locks cannot be overwritten by a new search. Even if a selected unlocked asset disappears from later result lists, it is retained and flagged `selection_retained_after_search=True` for verification; it is never silently substituted.

**Key limitations**

1. BF-S02 collects candidates; **it does not rank them semantically**. A provider's existing numerical score is not proof of relevance. Insertion order is a deterministic research ordering only. BF-S03 will compare metadata + real video frames with the visual constraints.
2. The adapter does not change the old scene-based discovery pipeline, the GUI, existing producer, F014 approvals, F021 verification, acquisition, CapCut or the timeline. The human review pool is only in-memory, not yet persisted.
3. A technical error is **not** semantic `no_match`; all missing candidate cases remain `no-candidates-found` or `technical-error-no-candidates`. No invented fallback footage.
4. No model is called to create BF-S01 plans at this phase. Synthetic plans are supplied by tests; actual user scripts stay local.
5. Live provider searches are possible **only** when a caller explicitly approves them and supplies configured providers. Any API service request may consume provider quota. Follow each provider's licensing/terms independently.
6. The service does not copy/rewrite/modify provider credentials, never includes API keys in diagnostics and does not upload frames or video.
7. Other editors/research PRs (BF-S01 PR #33, ZB-01 #30, ZB-02 #31, ZB-03A #32, F021 #29) are unchanged; **no merge**.

## Offline tests and acceptance gates

`tests/test_bf_s02_slot_candidates.py` uses only invented sample narration and fake Pexels/Pixabay providers. It asserts:

- explicit opt-in must be present **before** any provider call;
- 3 query axes are sent separately and each call is attributed to its slot;
- duplicate assets are merged within one slot but **not between** two slots;
- provider error text is not disclosed; failures cannot cause a random winner;
- disabled, missing, mismatched or stale provider data is handled without cross-slot mutation;
- a user's reviewed or locked choice cannot be silently overwritten;
- non-search editorial slots do not cause requests and remain visible in the pool;
- bounded call budget, stale-script invalidation and invalid inputs fail closed;
- no AI, internet request, download or FFmpeg is needed to run the offline suite.

Full Windows CI should also run inherited BF-S01 tests and production legacy regressions.

## Local offline check (only if a Windows research worktree has been created)

```powershell
$python = 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe'
$env:PYTHONPATH = 'D:\YouTubeTools\Bin_Finder_BFS02_Research\src'
& $python -m pytest -q 'D:\YouTubeTools\Bin_Finder_BFS02_Research\tests\test_bf_s02_slot_candidates.py'
```

The CLI opt-in provider pilot is now available, but **has not yet been run against real providers**. Real footage precision@3 / precision@5 benchmarks remain a follow-up acceptance gate. **Do not claim footage relevance improvement or automated timeline usability based on these tests.**

## Optional one-slot pilot (no automatic provider calls)

Module: `src/bin_finder/search/slot_search_smoke.py`.

**Default is offline**, showing the synthetic plan and its three distinct
queries, without reading provider credentials or accessing any provider:

```powershell
$python = 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe'
$env:PYTHONPATH = 'D:\YouTubeTools\Bin_Finder_BFS02_Research\src'
& $python -m bin_finder.search.slot_search_smoke --provider pexels
```

When a user explicitly chooses to run a real API pilot, they may add
`--approve-provider-calls` and `--project-root` pointing to the local
Bin Finder installation that already contains `config/providers.local.json`
or environment configuration. Pexels/Pixabay/local are the only allowed
pilot source choices, and **at most 3 search requests** are made for
**one synthetic slot**. Each request may consume provider API quota.

```powershell
& $python -m bin_finder.search.slot_search_smoke --provider pexels --project-root 'D:\YouTubeTools\Bin_Finder\Bin_Finder' --approve-provider-calls
```

The pilot prints candidate titles/source IDs and matched axes, but never
logs API secrets, complete raw payloads or temporary media download URLs.
Its candidates are not verified by VLM, licensed/approved, downloaded,
persisted, or converted to a video timeline. If no source is configured,
the outcome is `not-configured` with zero calls. The user can choose
to **not** run the live pilot until BF-S03 human evaluation is prepared.

`tests/test_bf_s02_slot_search_smoke.py` verifies offline default and
mocks the approved provider path in CI; it never sends network traffic.

## Next stage — BF-S03

Metadata filters (resolution, duration, suitability, provenance) → sample bounded local video frames → F021 local vision check against `must_show/must_not_show` → rank a **reviewable** top-N candidate pool with evidence explanations; maintain `no_match` for unverifiable content. Human-approved/locked selections remain authoritative. All real provider tests should run in explicit opt-in local research mode, separate from production.


## BF-S02 provider connectivity triage (2026-10-26)

On user Windows, the initial BF-S02 live pilot reported `provider-unavailable` for both Pexels and Pixabay and sent 0 API requests. After supplying runtime keys, each provider was called 3 times, but **all 6 attempts failed with `provider-error`** and no candidates. No actual footage relevance can be evaluated until this is resolved.

Research commit adds a bounded `--diagnose-single-query` flag to the same smoke CLI. **Only** in combination with `--approve-provider-calls`, this asks one configured provider **one** synthetic search question (`fishing boats harbor`), with `limit=1`, and prints a safe diagnostic code without URL, API key, HTTP response body or traceback. It does **not** download or select footage.

Examples of allowed output: `http-401`, `http-403`, `http-429`, `http-500`, `network-unreachable`, `timeout`, `invalid-json`, `invalid-response`, `unknown-provider-error`, `not-configured`, `ok`, `empty`. Status reflects a single API call, **not the correctness of searched footage**. Unknown ProviderError messages cannot disclose embedded secrets because only strictly allowlisted patterns are classified; unknowns are reduced to the fixed code.

One-call opt-in test (requires `PYTHONPATH` set to the pinned BF-S02 research worktree and keys available locally):

```powershell
& $python -m bin_finder.search.slot_search_smoke --provider pexels --project-root 'D:\YouTubeTools\Bin_Finder\Bin_Finder' --diagnose-single-query --approve-provider-calls
& $python -m bin_finder.search.slot_search_smoke --provider pixabay --project-root 'D:\YouTubeTools\Bin_Finder\Bin_Finder' --diagnose-single-query --approve-provider-calls
```

The existing per-axis search results also now contain `SearchAttempt.error_code` for supported sanitized `ProviderError` patterns. No production provider/HTTP implementation or GUI is changed. Credentials remain locally configured; **never paste tokens into GitHub, shell command arguments, public reports, or this chat.**

Interpretation: `401/403` suggests authorization, key scope or access rejection; `429` rate limits; `5xx` provider service errors; `network-unreachable/timeout` connectivity; `invalid-json` response format. The same result across both providers may reflect local network/proxy/TLS or incorrectly entered tokens, but **cannot be uniquely diagnosed from the old `provider-error` output**. No automatic retry or key rotation.


## BF-S02 minimal request isolation after HTTP 400 on both providers

The next user report showed `http-400` from both Pexels and Pixabay even with recognized runtime credentials. **This alone cannot prove bad credentials or bad query parameters.** Cross-check against the official provider API documentation:

- Pexels video search: `GET https://api.pexels.com/v1/videos/search`, `query` required, `per_page=1` accepted; `Authorization` must directly contain the API key without `Bearer`.
- Pixabay video search: `GET https://pixabay.com/api/videos/`, `key` required, `q` optional and `per_page` minimum 3. `min_height` is supported by videos. Queries are URL encoded by existing `JsonHttpClient`.

To isolate whether the **current optional size/search filters** trigger the error, a separate `--diagnose-minimal-request` mode sends **exactly one** documented minimal authenticated request:

```powershell
& $python -m bin_finder.search.slot_search_smoke --provider pexels --project-root 'D:\YouTubeTools\Bin_Finder\Bin_Finder' --diagnose-minimal-request --approve-provider-calls
& $python -m bin_finder.search.slot_search_smoke --provider pixabay --project-root 'D:\YouTubeTools\Bin_Finder\Bin_Finder' --diagnose-minimal-request --approve-provider-calls
```

Neither mode sends any request without explicit `--approve-provider-calls`. The minimal requests use **synthetic** `nature` rather than private narration:

- Pexels: `query=nature`, `per_page=1`; no size/orientation filter.
- Pixabay: `q=nature`, `per_page=3`; no size/video type/safesearch filter.
- Response never includes raw URL, API key, response body, exception trace or candidate metadata. Prints only `BFS02_PROVIDER_CALLS`, `BFS02_DIAGNOSTIC_CODE`, safe `BFS02_KEY_SHAPE` (if obvious accidentally entered `Bearer`, `key=`, quotes or placeholder), and `BFS02_PROXY_CONFIG_PRESENT` boolean (never proxy URL/user/password).
- `ok` means the API returned one or more **unverified candidates**, `empty` means no hits. Errors preserve the strict known-code allowlist: e.g. `http-400`, `http-401`, `http-403`, `network-unreachable`, `timeout`, `unknown-provider-error`.

**Interpretation:** if the simple request succeeds while the ordinary request fails, inspect optional request parameters. If **both still produce 400**, do *not* keep blindly changing search keywords; inspect whether credentials were copied to the correct provider and whether the network/proxy modifies requests. HTTP response bodies are intentionally hidden to prevent leaking Pixabay's query parameter key. The proxy boolean is a clue, not proof of a proxy-caused error.

The new tests mock the HTTP client; they do **not** hit either provider on GitHub CI.


## BF-S02 safe server-error-body classification (two minimal GETs, 2026-10-26)

Latest user Windows test: both Pexels and Pixabay returned HTTP 400 to the previous *minimal* `nature` queries, with no detected proxy and `KEY_SHAPE=unverified` (the latter does **not** mean keys are valid). Official API docs confirm the endpoints and minimal parameters are well-formed, so this is **not evidence of a broken query planner** or a bad video search term.

The normal Bin Finder `JsonHttpClient` intentionally sanitizes `HTTPError` down to `ProviderError("Provider: HTTP 400")`, losing the server's explanation. We now provide a **separate opt-in research diagnostic** `--diagnose-error-body`, implemented in `search/provider_error_probe.py`, WITHOUT touching that production client. It sends **one** minimal documented GET **only after** `--approve-provider-calls`, reads at most 2048 bytes of an HTTP error body and converts it to one of these **fixed hints**:

- `invalid-api-key-indicated` / `missing-api-key-indicated`: server text explicitly indicates key problems, not independent proof.
- `access-denied-indicated` / `rate-limit-indicated` / `edge-challenge-indicated`: server text suggests a permission/quota/edge response.
- `invalid-request-parameter-indicated`: server text suggests invalid request fields.
- `html-error-body` / `generic-bad-request` / `unclassified-error-body`: cannot infer the actual root cause.

The probe returns only `BFS02_DIAGNOSTIC_CODE`, `BFS02_SERVER_HINT`, bounded hit count, call count and provider name. **It never prints response body, full URL (Pixabay key is in the URL), HTTP headers, request headers, exception string, key, traceback or provider credentials**. Errors and unknown responses map to fixed codes. No persistence, retries, downloads or model calls. The upper success JSON size is bounded to 512 KiB.

```powershell
& $python -m bin_finder.search.slot_search_smoke --provider pexels --project-root 'D:\YouTubeTools\Bin_Finder\Bin_Finder' --diagnose-error-body --approve-provider-calls
& $python -m bin_finder.search.slot_search_smoke --provider pixabay --project-root 'D:\YouTubeTools\Bin_Finder\Bin_Finder' --diagnose-error-body --approve-provider-calls
```

**Important:** the keys must be available to this process through environment variables or local gitignored `config/providers.local.json`; they are not stored by the command. If `BFS02_SERVER_HINT=unclassified-error-body`, do not conclude the key is wrong or log raw bodies; the next manual step is checking the provider dashboards, API key type/account, or network path. User live pilot not yet rerun with this option; CI tests use injected fake HTTPError responses only.


## BF-S02.1 — Balanced Candidate Pool + Complete Research Report

**Motivation, grounded in actual user-local footage search:** after fixing local API key setup, the user ran BF-S02 using Pexels and Pixabay and obtained **6/6 successful searches** (3 axes × 2 sources). Each provider returned 5 per query and retained 10 total. Early printed titles were dominated by docked boats; titles alone did not verify the requested *boats entering the harbor at dawn*. The previous implementation admitted the first 10 unique results, so the **Action** axis could get zero slots if earlier Subject/Moment results filled the cap. The research CLI also displayed only the first 5 candidates.

**New selection policy:**
1. Run the same 3 bounded query axes per configured provider, with unchanged explicit approval, max request budget, validation and error handling. No extra API calls.
2. Deduplicate **within a slot** by `(provider, source_id)`, retaining first-seen metadata and *all* matched query axes. Different slots remain distinct. The full discovered pool is transient in memory, not a saved catalog.
3. After collecting all responses, choose up to `max_candidates_per_slot` hits by deterministic **axis-round-robin** `subject → moment → action`, one new asset per axis per cycle. For each axis prefer the provider having fewer already retained hits, using the configured provider order as a stable tie-breaker. If a bucket has no new hits, its unused opportunity flows to other axes. A multi-axis hit is selected only once.
4. The result's `hits` list is a **balanced review pool**, not metadata/VLM ranking, not approval and not necessarily the best actual footage. `CandidateHit.returned_order` still records first unique discovery order, independent of final pool order. Preserve locked/human-selected candidates via unchanged `CandidateReviewPool.apply_run`.
5. Report `unique_discovered`, `trimmed_by_cap`, `axis_discovered`, and a **complete numbered listing of ALL retained hits** (up to 10 in the existing CLI pilot), including title, ID, axes, reported duration/resolution/rights label. Source URLs, temporary download links, raw API responses, keys and request headers are never printed. A provider-supplied rights label is *not* licensing or final-selection approval. Each axis count is **non-exclusive**, since the same asset may match multiple queries.
6. A slot with all three independent pools of five, capped at ten, is expected to retain **4 Subject, 3 Moment, 3 Action** (15 unique found, 5 cap-trimmed). Two independent providers with 15 each and a 10-item cap are expected to yield roughly **5 per provider** under symmetric availability. Real-world overlap changes these distributions; the policy never fabricates a missing subject/moment/action candidate.

**Limits:** This is diversity-oriented pool selection, **not semantic ranking**. It cannot prove clip movement, camera perspective, time-of-day, actual footage licensing, or user top-3 preference. Future BF-S03 must compare the actual visual evidence against `must_show/must_not_show` and distinguish metadata relevance from video-frame support. The default research CLI remains offline and makes 0 provider calls without `--approve-provider-calls`. Previous API key override rules remain unchanged; when running a live pilot, be certain it reads the intended local `config/providers.local.json` and not stale process environment variables.

**Offline acceptance cases** in `tests/test_bf_s021_balanced_candidates.py` and `tests/test_bf_s02_slot_search_smoke.py` cover saturated 10-item cap, two-source fairness, three-axis duplication, tiny caps, missing-axis fallback, repeatability, provenance, human lock protection and complete secret-safe output. These tests use fake providers and do not call Pexels/Pixabay.

**Manual follow-up:** rerun the same live pilot in the isolated research worktree, compare axis counts and full 10-item listing against the previous report, and evaluate representative footage frames/preview before interpreting semantic accuracy. Do not merge the research PR until real relevance measurements are available.
