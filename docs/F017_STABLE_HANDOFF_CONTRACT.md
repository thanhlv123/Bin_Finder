# F017 — Stable Handoff Contract & Portable Footage Package

Status: **PASS (Windows CI + real FFmpeg handoff acceptance).**

Verified acceptance: Windows CI run #157, run ID 39816530610, status SUCCESS;
471 passed, 0 skipped, 0 failed; pinned FFmpeg 9.0.2 with SHA-256 verified; real
smokes `PASS_F015_REAL_FFMPEG`, `PASS_F016_RESTORE_EXPORT`, `PASS_F017_REAL_HANDOFF`.
This is not AI_Video_Editor integration: F017 ends at the portable verified footage
package.

Bin Finder ends at an **approved + verified + portable footage package**.
AI_Video_Editor later begins at **validated import of `bin_finder_handoff_v1`**.
F017 does not invoke, import or modify AI_Video_Editor, and the legacy
`ai_video_editor_bin_finder_adapter_v1` is unchanged.

## Package

```text
library/
  footage/scene_001.mp4 ...
  footage_manifest.json            # F015, bin_finder_final_export_v1 unchanged
  footage_index.csv                # optional F015
  _bin_finder_handoff.json         # NEW, only when ExportOptions(handoff=True)
  _ai_video_editor_bin_finder_adapter.json / _bin_finder_acceptance.json  # only on request
```

All F017 paths are package-relative, forward-slash, and must be exactly
`footage/<name>.mp4`. Absolute paths, drive letters, backslashes, `.`/`..`, other
layouts and Windows reserved names are rejected. The package stays valid after the
whole folder is moved or renamed.

## `bin_finder_handoff_v1`

Top level: `format`, `producer`, `project_id`, `ready`, `scene_count`, `clip_count`,
`total_duration_seconds`, `manifest_relative_path`, `manifest_sha256`, `scenes`.
`manifest_sha256` binds the handoff to the exact `footage_manifest.json`.

Each scene: `scene_id`, `scene_order`, `script_text`, `vietnamese_text`,
`target_duration_seconds`, `footage`.

`footage`: `clip_id`, `relative_path`, `exported_file_sha256`, `byte_count`,
`duration_seconds`, `provider`, `source_id`, `semantic_score`, `vlm_score`,
`final_score`, `rights_status`, `creator`, `original_source_start_seconds`,
`original_source_end_seconds`, `original_source_media_sha256`; plus optional
`source_url` and `provenance` (allowlist: `license_basis`, `license_url`,
`creator_url`, `usage_authorization`, `asset_id`, `creator_id`) when extended
metadata is enabled. URLs never carry a query or fragment. No title, raw provider
response, credentials, Authorization data or local paths are written. Known
`BIN_FINDER_*KEY/SECRET` values are redacted. Unknown keys are rejected: the schema is
closed, so additive changes require a new format version.

Exported files are independent trimmed clips (local 0→duration). The `original_source_*`
fields keep the original source coordinates and hash for traceability.

## Relationship to F015 / F010

`FinalExportService` builds the handoff inside the existing F015 staging directory,
after the manifest, CSV and optional adapter, using already-extracted files and rows.
Nothing is extracted again, no new FFmpeg code exists, and F010 is **not** re-run on
materialized coordinates; READY on original source coordinates remains authoritative
and is only echoed. The producer then runs the verifier on staging; any failure
(`handoff-invalid`, write error) publishes no library and cleans staging as before.
`ExportOptions.handoff` defaults to `False`; F015 behavior and `FinalExportResult`
positional fields are unchanged (`handoff_path` is appended). The seven-panel GUI is
unchanged and has no handoff control yet.

## Verifier

`verify_handoff_package(path) -> HandoffReport` is read-only: it never repairs,
searches, downloads or rewrites. It raises `HandoffError(code)` on the first problem:
missing/malformed/oversized JSON, duplicate keys, NaN/Infinity, unsupported format,
unknown keys, `ready != true`, zero scenes, count mismatch, duplicate scene/clip IDs,
bad ordering, unsafe or escaping paths, linked (symlink/junction) package root or path
components, missing/empty/non-regular files, byte-count and SHA-256 mismatch,
non-finite durations or scores, scores outside 0–1, invalid original ranges,
missing/modified/inconsistent `footage_manifest.json` (format, project, counts,
scene/clip identity, exported path/filename, rights, creator, scores, hashes),
unsafe provenance, and path-too-long / OS errors. Links above the package root are
not inspected. Extra unreferenced files are ignored.

## Acceptance

`python -m bin_finder.handoff_smoke --approve-test-export` runs synthetic A–B–A
(original 10→15, 0→5, 30→35; package 0→5 each) through F010 READY, real F015 export,
handoff, verify PASS, move/rename and verify PASS, tampered MP4 FAIL, missing MP4
FAIL. Without the flag it prints `SKIPPED_NOT_APPROVED`; without FFmpeg it prints
`SKIPPED_NO_FFMPEG` and exits 2. CI runs it with the pinned FFmpeg 9.0.2 and fails
if it or its pytest counterpart is skipped.

Tests: `tests/test_handoff_f017.py` (verifier matrix), `tests/test_handoff_export_f017.py`
(staging transaction, secrets, F015/F010 regression, real FFmpeg).

## Notes and limitations

- `docs/F014_WORKFLOW_REVIEW_FINAL_SELECTION.md` still says final selections are
  "session-only"; that was superseded by F016 and is intentionally not edited here.
- The verifier proves package integrity, not copyright; rights fields are carried
  data. Hashing assumes application-controlled storage.
- No GUI toggle, no importer, no AI_Video_Editor integration, no concurrency or
  power-loss changes to F015 publication.
