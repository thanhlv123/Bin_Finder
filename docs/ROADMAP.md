# Bin Finder roadmap

The accepted F001.5 workspace layout remains fixed unless a real usability bug requires a change.

- F001: GUI shell, project/scene models, selected-footage library contract. **PASS**
- F002: Real discovery providers for YouTube / Storyblocks / Pexels / Pixabay / Local; News deferred. **PASS**
- F003: Candidate intelligence foundation — content hash, FFprobe metadata, timed transcript sidecars, shot boundaries, reusable analysis cache. **IN PROGRESS**
- F004: Hybrid retrieval — transcript semantic relevance + exact/BM25-style lexical relevance + visual embedding provider contract + score fusion.
- F005: VLM verification/reranking — subject, action, location, object, time, visual quality, conflict penalties, confidence thresholds.
- F006: Smart clip extraction — target 5.0s, 3.5–7.0s bounds, shot-aware trim, natural-action preference.
- F007: Local footage intelligence — incremental indexing, local-first search, content-hash reuse, search-by-image.
- F008: Source diversity — anti-adjacent reuse, anti-overlap, source cooldown, duplicate suppression.
- F009: Preview/accept/reject and A/B quality-evaluation workflow.
- F010: Real 1–3 minute script acceptance, tuning, and stable manifest adapter for AI_Video_Editor.

## Architecture principles learned from public footage-search projects

Bin Finder follows a clean-room design inspired by common retrieval patterns:

1. Discovery first, acquisition authorization separately.
2. Metadata search narrows candidate videos but does not prove visual relevance.
3. Candidate videos are split into real shots before semantic/VLM scoring.
4. Hybrid retrieval combines transcript, lexical, and visual evidence.
5. A slower VLM verifies only the strongest candidates.
6. Content hashes and analyzer versions prevent unnecessary re-analysis.
7. The final selector enforces source diversity and non-overlapping ranges.
