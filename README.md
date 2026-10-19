# Bin Finder

Bin Finder is a Windows-local desktop application for discovering, analyzing, reviewing, selecting, and exporting script-matched footage.

## Current milestone status

- **F001.5 GUI workspace:** PASS
- **F002 provider discovery:** PASS
- **F003 candidate intelligence:** PASS
- **F004 hybrid retrieval:** PASS
- **Next:** F005 VLM verification/reranking

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
  -> VLM verification
  -> selected-footage filmstrip
  -> clean export library + manifests
```

## Candidate intelligence

F003 adds a backend-only analysis layer for local or otherwise authorized media:

- SHA-256 content identity
- FFprobe metadata
- SRT/VTT timestamped transcript sidecars
- FFmpeg scene-change shot boundaries
- SQLite analysis cache keyed by media + transcript identity + analyzer version

## Hybrid retrieval

F004 ranks exact shot/time ranges using:

- BM25 relevance
- exact scene-context phrase matches
- pluggable text similarity
- pluggable visual similarity
- normalized weighted fusion
- a retrieval evaluation harness reporting Top-1 accuracy, Recall@K, and MRR

The default text scorer is dependency-free. The visual scorer is a provider contract until a visual embedding runtime is approved.

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
