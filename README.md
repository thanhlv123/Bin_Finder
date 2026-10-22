# Bin Finder

Bin Finder is a Windows-local desktop application for discovering, analyzing, reviewing, selecting, and exporting script-matched footage.

## Current milestone status

- **F001.5 GUI workspace:** PASS
- **F002 provider discovery:** PASS
- **F003 candidate intelligence:** PASS
- **F004 hybrid retrieval:** PASS
- **F005 context verification / VLM reranking contract:** PASS
- **F006 smart clip planning/extraction:** PASS
- **F007 local footage intelligence:** PASS
- **F008 source diversity:** PASS
- **F009 human review / A-B evaluation:** PASS
- **F010 acceptance gate / AI_Video_Editor adapter:** PASS
- **F014 workflow review / explicit final clip selection:** PASS (offline)
- **F015 final footage export library:** PASS (offline + real FFmpeg smoke)
- **F016 session persistence / recovery:** PASS (Windows CI 407 passed, 0 skipped + real FFmpeg restore/export smoke)
- **F017 stable handoff contract / portable package:** implemented, local acceptance PASS (Windows CI pending)

Candidate approval for acquisition/analysis is separate from final clip approval.
Only explicitly approved, verified local clip proposals create final selections
and count toward F010 readiness. Package handoff remains an explicit READY-only
action. See [F014 details](docs/F014_WORKFLOW_REVIEW_FINAL_SELECTION.md).

Panel 7 now explicitly exports READY final selections through the existing F006
extractor into one MP4 per scene, with an atomic completion manifest and optional
CSV index. Source hashes are revalidated; incomplete, cancelled or failed runs
publish no completed library, and existing completed exports are never overwritten.
An optional F010 adapter references the extracted files with local 0-based ranges,
using the original source-coordinate readiness report. Original source ranges and
hashes remain in the F015 manifest. No final video is rendered. See
[F015 usage and offline FFmpeg acceptance](docs/F015_FINAL_FOOTAGE_EXPORT.md).

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
  -> local-first indexed discovery
  -> external providers only when local is insufficient
  -> normalized candidate records
  -> candidate analysis
  -> shot-level hybrid retrieval
  -> top-N context/VLM verification
  -> smart 3.5–7.0 second clip proposal
  -> source diversity / anti-overlap
  -> human review / evaluation
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

## Smart clips

F006 keeps complete shots when they already fit the 3.5–7.0 second duration policy. Longer shots receive a 5-second window around an optional evidence anchor; shorter shots are rejected by default rather than crossing a visual cut. A safe FFmpeg backend can extract approved local/authorized ranges without overwriting existing output by default.

## Local footage intelligence

F007 adds an incremental SQLite index for the configured local library. Unchanged files are not re-hashed, transcript sidecar changes refresh without re-hashing video bytes, and renamed files retain the same content-based source ID. When a strong local match reaches the default threshold, network providers can be skipped for that scene.

F007 also exposes local search-by-image using a cached perceptual frame-hash baseline. It is intended for near-duplicate/appearance matching, not semantic CLIP search.

## Source diversity

F008 enforces the final source-rotation rules. The same source cannot be adjacent by default, overlapping time ranges from the same source are rejected, duplicate groups can suppress repeated visuals, and near-identical same-source ranges are collapsed. A lower-ranked alternative is used only when it stays within the configured quality-drop guardrail; otherwise the scene remains unresolved instead of forcing poor footage.

## Human review

F009 persists accepted, rejected, and waitlist decisions and records A/B preferences for candidates from the same scene. The controls fit inside the existing review action row, so the accepted panel geometry is unchanged. Review data is stored outside the repository in the local Bin Finder application-data area.

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

## Acceptance and integration contract

F010 adds a strict 1–3 minute acceptance gate, per-scene readiness reporting, score/coverage metrics, rotation/overlap validation, and a versioned `ai_video_editor_bin_finder_adapter_v1` manifest. Bin Finder still does not modify AI_Video_Editor; the adapter is the stable handoff contract for the later integration step after Windows acceptance.

F016 session persistence and recovery: **PASS**. Atomic session snapshots now include allowlisted explicit local final selections. On restore, SHA-256 and local path safety are rechecked; missing/changed media and remote-origin selections without independent F012 proof remain unresolved. GUI session lifecycle now restores validated scenes/filmstrip and recomputes F010/F015 readiness; remote F012 selections require independent F012 cache-manifest and SHA-256
revalidation. F013 workflow references restore as historical identity/hash
hints, never as analysis or approvals. Over-long media paths (Windows MAX_PATH /
WinError 206) fail closed as unresolved, and an offline real-FFmpeg smoke
(`bin_finder.session_export_smoke`) chains restore -> SHA-256 revalidation -> F010 READY ->
real F015 export. READY is never persisted; it is always recomputed. See
[F016 details](docs/F016_SESSION_RECOVERY.md).

F017 stable handoff: an F015 export can additionally write `_bin_finder_handoff.json`
(`bin_finder_handoff_v1`) with package-relative paths, hashes and byte counts, and
`verify_handoff_package()` checks it read-only after the folder is moved. Bin Finder
ends at an approved, verified, portable footage package; AI_Video_Editor later starts
at validated import. Legacy adapter v1 is unchanged. See
[F017 details](docs/F017_STABLE_HANDOFF_CONTRACT.md).

See `docs/ROADMAP.md` for the milestone plan.
