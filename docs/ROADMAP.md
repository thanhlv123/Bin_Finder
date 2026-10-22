# Bin Finder roadmap

The accepted F001.5 workspace layout remains fixed unless a real usability bug requires a change.

- F001: GUI shell, project/scene models, selected-footage library contract. **PASS**
- F002: Real discovery providers for YouTube / Storyblocks / Pexels / Pixabay / Local; News deferred. **PASS**
- F003: Candidate intelligence foundation — content hash, FFprobe metadata, timed transcript sidecars, shot boundaries, reusable analysis cache. **PASS**
- F004: Hybrid retrieval — transcript/text similarity + exact/BM25 lexical relevance + visual scoring provider contract + score fusion + retrieval evaluation harness. **PASS**
- F005: Context verification/VLM reranking contract — subject, action, location, object, time, visual quality, conflict penalties, confidence thresholds, safe fallback. **PASS**
- F006: Smart clip planning/extraction — target 5.0s, 3.5–7.0s bounds, shot-aware trim, optional anchor time, safe local FFmpeg extraction. **PASS**
- F007: Local footage intelligence — incremental indexing, local-first search, content-hash reuse, transcript-aware refresh, perceptual search-by-image baseline. **PASS**
- F008: Source diversity — source cooldown, anti-adjacent reuse, anti-overlap, duplicate suppression, quality guardrails, unresolved flags. **PASS**
- F009: Human review — persistent accept/reject/waitlist decisions, A/B comparisons, evaluation summaries, compact review controls. **PASS**
- F010: Real 1–3 minute script acceptance, unresolved-scene gating, quality metrics, and stable AI_Video_Editor manifest adapter. **PASS**

F014: Workflow review and explicit final clip selection integration. **PASS (offline)**.
Reuses F008 diversity and F010 acceptance/adapter; candidate acceptance remains
separate from final clip approval. See
[F014 contract](F014_WORKFLOW_REVIEW_FINAL_SELECTION.md).

F015: Final footage export library. **PASS (offline + real FFmpeg smoke)**.
READY-only explicit export reuses F006 extraction, validates approved source
hashes, publishes a complete scene-ordered library atomically, and writes a
versioned manifest with optional CSV and materialized F010 adapter. Cooperative
QThread cancellation leaves no completed partial library. Original F010 source
coordinates authorize export; adapter coordinates are local to trimmed clips.
A–B–A passes without changing F010 overlap semantics or adapter v1. Acceptance:
53 focused passed, 363 full regression passed, one Windows symlink-privilege skip;
real offline FFmpeg A–B–A smoke passed. See
[F015 contract](F015_FINAL_FOOTAGE_EXPORT.md).

F016: Versioned session persistence and recovery. **PASS (Windows CI + real FFmpeg smokes)**. Scene/UI snapshots and allowlisted final-selection serialization with local SHA-256 revalidation are implemented; remote F012 cache proof is implemented; MAX_PATH paths fail closed; offline real-FFmpeg
restore -> SHA-256 revalidation -> F010 READY -> F015 export smoke passes. READY is never
persisted and is always recomputed. Acceptance: Windows CI 407 passed, 0 skipped (pinned
FFmpeg 9.0.2, SHA-256 verified); real F015 and F016 restore/export smokes PASS.
Validated F013 workflow identity/hash references are historical hints only,
not restored approvals.
GUI lifecycle restores validated state and recomputes F010/F015 readiness. See [F016 contract](F016_SESSION_RECOVERY.md).

F017: Stable handoff contract and portable footage package. **PASS (Windows CI +
real FFmpeg handoff acceptance)**: run #157 (ID 39816530610) success, 471 passed,
0 skipped, 0 failed, pinned FFmpeg 9.0.2 SHA-256 verified; F015/F016/F017 real smokes
PASS. AI_Video_Editor integration is not part of F017. Opt-in `_bin_finder_handoff.json`
(`bin_finder_handoff_v1`) built inside the F015 staging transaction, package-relative
paths, read-only `verify_handoff_package()`, real FFmpeg move/tamper/missing smoke.
Legacy adapter v1 and F010/F014/F015/F016 semantics unchanged. See
[F017 contract](F017_STABLE_HANDOFF_CONTRACT.md).

F018: Production script scene planning and context enrichment. **Implemented; local
acceptance PASS, Windows CI pending**. Deterministic `scene_planning` replaces the GUI
prototype split (3.5–7.0 s scenes aligned to one F006 clip each; long narration splits into more scenes); raw scenes carry searchable context and a documented heuristic
verification fallback. F010 60–180 s policy untouched; F019 owns long-form acceptance.
See [F018 contract](F018_PRODUCTION_SCENE_PLANNING.md).

F019: Production long-form acceptance policy. **Implemented; local acceptance PASS,
Windows CI pending**. F010 default stays 60–180 s; GUI readiness and F015 export use
`production_acceptance_policy()` (min 60 s, no upper ceiling). Other gates, F014, F006,
F017 schemas unchanged. See [F019 contract](F019_LONG_FORM_ACCEPTANCE.md).

## Architecture principles learned from public footage-search projects

Bin Finder follows a clean-room design inspired by common retrieval patterns:

1. Discovery first, acquisition authorization separately.
2. Metadata search narrows candidate videos but does not prove visual relevance.
3. Candidate videos are split into real shots before semantic/VLM scoring.
4. Hybrid retrieval combines transcript, lexical, and visual evidence.
5. Retrieval changes are measured with Top-1, Recall@K, and MRR before replacing defaults.
6. A slower verification stage reranks only the strongest candidates and safely falls back on provider failure.
7. Smart clip planning preserves natural shot boundaries whenever the shot fits the duration policy.
8. Local indexing is incremental and uses content identity to avoid unnecessary rework.
9. Local-first discovery can skip external APIs when a strong local match already exists.
10. Final selection enforces source diversity and non-overlapping ranges without forcing low-quality alternatives.
