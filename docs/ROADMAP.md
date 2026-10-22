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

F016: Versioned session persistence and recovery. **IN PROGRESS**. Scene/UI snapshots and allowlisted final-selection serialization with local SHA-256 revalidation are implemented; remote proof, GUI restore, workflow references and final Windows acceptance remain. See [F016 contract](F016_SESSION_RECOVERY.md).

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
