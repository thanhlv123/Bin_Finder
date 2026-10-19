# Bin Finder

Bin Finder is a Windows-local desktop application for discovering, analyzing, reviewing, selecting, and exporting script-matched footage.

## Current milestone status

- **F001.5 GUI workspace:** PASS
- **F002 provider discovery:** PASS
- **F003 candidate intelligence:** PASS
- **F004 hybrid retrieval:** PASS
- **F005 context verification / VLM reranking contract:** PASS
- **Next:** F006 smart clip extraction

The accepted GUI layout remains fixed. New retrieval capabilities are added behind the existing panels rather than redesigning the workspace.

## Current discovery sources

- YouTube Data API v3 — discovery/metadata only
- Storyblocks API v2
- Pexels Video API
- Pixabay Video API
- Local footage library
- News/electronic newspapers — visible in the GUI but backend intentionally deferred

## Workflow

```text
Script scene
  -> scene context / queries
  -> local + enabled provider discovery
  -> normalized candidate records
  -> candidate analysis
  -> shot-level hybrid retrieval
  -> top-N context/VLM verification
  -> smart clip proposal
  -> selected-footage filmstrip
  -> clean export library + manifests
```

## Candidate intelligence

F003 adds SHA-256 media identity, FFprobe metadata, timestamped SRT/VTT transcript sidecars, FFmpeg shot boundaries, and a transcript-aware SQLite cache.

## Hybrid retrieval

F004 ranks exact shot/time ranges using BM25, exact scene-context phrases, pluggable text similarity, pluggable visual similarity, normalized weighted fusion, and a Top-1 / Recall@K / MRR evaluation harness.

## Context verification

F005 adds a top-N verification contract with separate scores for subject, action, location, objects, time, visual quality, and context conflict. Provider failures fall back safely to F004 order.

The current default verifier is a dependency-free transcript/metadata heuristic. A future local or cloud VLM can implement the same interface without changing the retrieval engine or GUI.

No generic remote downloader is included.

## Stable GUI rules

The seven workflow panels stay in the accepted F001.5 layout:

1. Dự án & Kịch bản
2. Danh sách cảnh trong kịch bản
3. Tùy chọn tìm kiếm & nguồn
4. Kết quả tìm kiếm
5. Xem, phân tích & đánh giá cảnh
6. Danh sách cảnh đã chọn
7. Xuất footage

The search-results grid remains exactly three cards per row. Review/export geometry remains fixed.

## Stable selection rules

- `scene_id` stays stable when footage is replaced.
- `clip_id` identifies one concrete selected clip.
- Adjacent scenes may not reuse the same source video.
- The same source may return after at least one different source.
- Overlapping ranges from the same source are invalid.
- Final output is a clean folder containing approved clips plus machine-readable manifests.

## Provider secrets

Provider credentials are loaded from environment variables or the gitignored `config/providers.local.json`. Secrets must never be committed, printed, or written into candidate/manifest data.

## Windows

Python 3.12 + PyQt6. Run:

```powershell
& ".\start_bin_finder.cmd"
```

See `docs/ROADMAP.md` for the milestone plan.
