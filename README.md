# Bin Finder

Bin Finder is a Windows-local application whose 1.0 goal is **script -> finished video**: AI visual briefs per sentence or narration phrase; multi-source footage discovery (Pexels, Pixabay, Coverr, Wikimedia Commons, Storyblocks when an API is available, and switchable YouTube); two-stage matching (fast embedding filtering, then VLM verification of the top 3); human or AI selection; TTS voice; voice-timed editing with effects, music and subtitles; quality checks; and MP4 + credits export.

The 1.0 pipeline must also run headlessly with one `bin_finder run` command. Acceptance requires a complete real video approved by the project owner. These are roadmap goals; the merged implementation currently provides the footage discovery, review and portable export foundation.

## Current milestone status

See the [v2 roadmap and milestone history](docs/ROADMAP.md) for R0-R7, completion criteria and retained research ideas. F001-F021 are merged with CI passing (F021 real-footage accuracy not yet validated). R0 aligns documentation, version and CI with the new direction.

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
hashes remain in the F015 manifest. The current footage export does not yet render a final video; R4-R6 add production and headless delivery. See
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
  -> clean export library + manifests (current foundation)
  -> TTS voice + voice-timed editing / effects / music / subtitles (v2 goal)
  -> quality checks -> MP4 + credits (v2 goal)
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
- The footage library is a clean folder containing approved clips plus machine-readable manifests; the 1.0 final delivery adds MP4 + credits.

## Provider secrets

Provider credentials are loaded from environment variables or the gitignored `config/providers.local.json`. Secrets must never be committed, printed, or written into candidate/manifest data.

## Windows

Python 3.12 + PyQt6. Run:

```powershell
& ".\start_bin_finder.cmd"
```

## Acceptance and integration contract

F010 adds a strict 1–3 minute acceptance gate, per-scene readiness reporting, score/coverage metrics, rotation/overlap validation, and a versioned `ai_video_editor_bin_finder_adapter_v1` manifest. Bin Finder still does not modify AI_Video_Editor; the adapter is the existing compatibility integration adapter; the portable contract intended for a future AI_Video_Editor import is `bin_finder_handoff_v1` (F017).

F016 session persistence and recovery: **PASS**. Atomic session snapshots now include allowlisted explicit local final selections. On restore, SHA-256 and local path safety are rechecked; missing/changed media and remote-origin selections without independent F012 proof remain unresolved. GUI session lifecycle now restores validated scenes/filmstrip and recomputes F010/F015 readiness; remote F012 selections require independent F012 cache-manifest and SHA-256
revalidation. F013 workflow references restore as historical identity/hash
hints, never as analysis or approvals. Over-long media paths (Windows MAX_PATH /
WinError 206) fail closed as unresolved, and an offline real-FFmpeg smoke
(`bin_finder.session_export_smoke`) chains restore -> SHA-256 revalidation -> F010 READY ->
real F015 export. READY is never persisted; it is always recomputed. See
[F016 details](docs/F016_SESSION_RECOVERY.md).

F017 stable handoff: **PASS** (Windows CI run #157, 471 passed, 0 skipped, plus real
FFmpeg F015/F016/F017 smokes). An F015 export can additionally write
`_bin_finder_handoff.json` with package-relative paths, hashes and byte counts, and
`verify_handoff_package()` checks it read-only after the folder is moved. Two
contracts coexist, and neither schema changed:

- `ai_video_editor_bin_finder_adapter_v1` — the existing/legacy compatibility
  integration adapter (F010).
- `bin_finder_handoff_v1` — the portable contract intended for a future
  AI_Video_Editor import.

The existing F017 stage produces an approved, verified, portable footage package.
The v2 roadmap extends Bin Finder through final video production; an AI_Video_Editor
consumer remains outside 1.0. See
[F017 details](docs/F017_STABLE_HANDOFF_CONTRACT.md).

F018 scene planning: the script-splitting action now uses the deterministic
`bin_finder.scene_planning` planner (paragraphs, `. ! ?`, abbreviation/decimal safety,
bounded grouping, 3.5–7.0 s duration estimate (one scene = one F006 clip; long narration becomes more scenes), conservative text-derived context with a
keyword fallback) instead of the prototype period split. No LLM/VLM, no new dependency;
F010 acceptance and F014 explicit approval are unchanged. See
[F018 details](docs/F018_PRODUCTION_SCENE_PLANNING.md).

F019 long-form acceptance: F010's default (`evaluate_project(project)`) still means a
60–180 s project. GUI readiness and final export now use
`production_acceptance_policy()`: at least 60 s and no artificial 180 s ceiling, with
coverage, score, rotation and overlap gates unchanged. Structural bounds (F018 input
and scene limits, session limits) still apply. See
[F019 details](docs/F019_LONG_FORM_ACCEPTANCE.md).

F020 portable handoff GUI: Panel 7 has a "Tạo gói handoff portable" checkbox, checked by
default, which makes a normal GUI export write `_bin_finder_handoff.json`
(`bin_finder_handoff_v1`). The core `ExportOptions().handoff` stays `False`, and the legacy
`ai_video_editor_bin_finder_adapter_v1` option remains separate and independent.
AI_Video_Editor consumer integration is not implemented. See
[F020 details](docs/F020_PORTABLE_HANDOFF_GUI.md).

F021 real VLM verification: the production workflow now verifies actual video frames with
an optional local Ollama vision model (default `qwen3-vl:4b`, loopback only, stdlib HTTP, FFmpeg
frame sampling), per-unit falling back to the heuristic verifier when Ollama, the model, FFmpeg
or the response is unavailable. F005 remains the provider contract, F018 the text fallback, and
F014 human approval is still required. No cloud upload, no model auto-install, no new dependency.
The live pipeline smoke passed against local `qwen3-vl:4b`; accuracy on real footage has not been validated. The default `qwen3-vl:4b` is a Thinking model, so requests use `num_ctx` 8192 and `num_predict` 2048 (overridable via `BIN_FINDER_VLM_NUM_CTX` / `BIN_FINDER_VLM_NUM_PREDICT`). See [F021 details](docs/F021_REAL_VLM_VERIFICATION.md).

See the [v2 roadmap](docs/ROADMAP.md) for the milestone plan.

## Visual brief (R1)

Generate sentence-level cues, visual briefs and source-specific English footage queries:

```powershell
.\.venv\Scripts\python.exe -m bin_finder.brief script.md -o briefs.json --csv briefs.csv --provider heuristic
```

Copy `config/planning.example.json` to `config/planning.local.json` under `--project-root` (default: current directory). All settings accept `BIN_FINDER_PLANNING_<FIELD>` environment overrides; sources accept a JSON array or comma-separated names. For an OpenAI-compatible API, set `api_base_url` (including `/v1` if needed), `api_model`, and `BIN_FINDER_PLANNING_API_KEY`. Credentials are excluded from plan output and config repr.

`auto` checks the configured Ollama model, then configured API, then offline heuristic. Failed or invalid LLM cues fall back individually, with reasons in `notes`. `fallback_count` counts heuristic cues when LLM/auto was requested (zero for explicit heuristic). JSON includes stable sequential cue IDs, original narration, SHA-256 of the full script and schema version `brief_plan_v1`. IDs are reproducible for the same script; inserting earlier narration can renumber later cues. A chapter containing fewer than three words remains a short cue to preserve its narration and chapter. Heuristic briefs need editorial review, especially abstract or negated statements; they do not verify footage or authorize acquisition.

## Footage sources (R2)

Run `python -m bin_finder.footage BRIEFS.json -o FOOTAGE.json --credits credits.txt`.
Copy `config/footage.example.json` to the project's `config/footage.local.json`;
select it with `--project-root PATH`. Provider credentials use the existing provider
configuration; Coverr also accepts `BIN_FINDER_COVERR_API_KEY`. Commons needs no key.
Settings accept `BIN_FINDER_FOOTAGE_*` overrides (sources are comma separated).
Use `--sources pexels,coverr`, `--limit-cues N`, or `--youtube` / `--no-youtube`.
YouTube is disabled by default, even when listed in sources; enabling it adds
reference metadata only, never download or usage permission.
The JSON carries per-candidate licenses, reference flags and per-cue errors for R3.
`credits.txt` groups unique sources with creator and license links. Discovery license
metadata does not replace acquisition authorization or final clip approval.

## Matching & selection (R3)

`min_vlm_score` defaults to 0.7 (0..1, env `BIN_FINDER_MATCH_MIN_VLM_SCORE`): with VLM enabled, auto-selection requires a `match`/`partial` verdict meeting this score and `auto_select_threshold`; the cue flag `vlm_missing` means no verdicts are available, or `--no-vlm` is active.

```powershell
python -m bin_finder.matching footage.json --briefs briefs.json -o selection.json --html review.html --no-vlm
python -m bin_finder.matching footage.json --briefs briefs.json -o selection.json --html review.html --decisions decisions.json
```

Luồng duyệt: footage → matching → mở `review.html` → chọn/khóa/bỏ chọn → tải `decisions.json` → chạy lại với `--decisions`.
Trang HTML chứa CSS/JS, preview phát trực tiếp từ URL HTTPS của nhà cung cấp. Các nút chỉ thay đổi quyết định trong trình duyệt cho tới khi tải JSON.

Cấu hình: sao chép `config/matching.example.json` thành `config/matching.local.json`; biến `BIN_FINDER_MATCH_*` ghi đè từng trường (boolean: `true`/`false`; hosts: JSON hoặc phân cách dấu phẩy).
VLM bật mặc định, dùng cấu hình F021: `BIN_FINDER_OLLAMA_URL`, `BIN_FINDER_VLM_MODEL` (mặc định `qwen3-vl:4b`), cùng các biến timeout/context F021. Không đọc planning.local.json. `--no-vlm` chạy hoàn toàn offline.
Tầng 1 hiện là lexical: 0.35 BM25 + 0.25 must-show phrase + 0.35 action + chất lượng tối đa 0.05 − 0.15 mỗi token avoid; giới hạn 0.39 nếu thiếu động từ hành động. Điểm cuối có VLM là 0.4 text + 0.6 VLM, thiếu VLM dùng text và cờ `vlm_missing`.
Thumbnail không chứng minh chuyển động; kết quả uncertain cần duyệt. YouTube chỉ tham khảo. Selection không cấp quyền tải/dựng; nếu phải dùng lại nguồn thì đánh dấu overlap chưa kiểm chứng. Khóa được áp lại từ decisions khi ID vẫn nằm trong Top K; ID ngoài Top K được cảnh báo, không tự thay thế.
R1 có `retry_single` mặc định bật: mỗi cue LLM lỗi được thử riêng một lần; lỗi kết nối dừng gọi tiếp.
