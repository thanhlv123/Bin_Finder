# Bin Finder roadmap

The accepted F001.5 workspace layout remains fixed unless a real usability bug requires a change.

- F001: GUI shell, project/scene models, selected-footage library contract. **PASS**
- F002: Real discovery providers for YouTube / Storyblocks / Pexels / Pixabay / Local; News deferred. **PASS**
- F003: Candidate intelligence foundation — content hash, FFprobe metadata, timed transcript sidecars, shot boundaries, reusable analysis cache. **PASS**
- F004: Hybrid retrieval — transcript/text similarity + exact/BM25 lexical relevance + visual scoring provider contract + score fusion + retrieval evaluation harness. **PASS**
- F005: Context verification/VLM reranking contract — subject, action, location, object, time, visual quality, conflict penalties, confidence thresholds, safe fallback. **PASS**
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
5. Retrieval changes are measured with Top-1, Recall@K, and MRR before replacing defaults.
6. A slower verification stage reranks only the strongest candidates and safely falls back on provider failure.
7. Content hashes and analyzer versions prevent unnecessary re-analysis.
8. The final selector enforces source diversity and non-overlapping ranges.
