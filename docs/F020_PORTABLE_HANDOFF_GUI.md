# F020 — Portable Handoff GUI

Status: implemented; local acceptance PASS (Windows CI pending until pushed).

## Problem
F017 added `bin_finder_handoff_v1` and `ExportOptions(handoff=True)` in the core, but
Panel 7 never passed `handoff=True`, so a normal GUI export did not create
`_bin_finder_handoff.json`.

## What F020 does
- Panel 7 gains one checkbox, `ExportPanel.handoff_option`, labelled
  **"Tạo gói handoff portable"**, **checked by default**. It sits under the destination
  field; the seven-panel layout and Panel 7's fixed 168 px height are unchanged.
- `MainWindow._export_final()` now builds
  `ExportOptions(csv_index, integration_adapter, scene_id_filenames, include_metadata, handoff=<checkbox>)`.
  The GUI only selects the option; `FinalExportService` (F015 staging, F017 build and
  self-verification, atomic publish, cancellation, failure handling) is unchanged and
  authoritative. The GUI never calls `build_handoff()`.
- On success with a handoff the status reads "Đã xuất footage · Handoff portable".
- Core `ExportOptions().handoff` **remains `False`**: F017's core stays explicitly opt-in;
  only the production GUI opts in by default.

## Two different contracts
| Option | Contract | File |
|---|---|---|
| Tạo gói handoff portable (default on) | `bin_finder_handoff_v1` — portable, package-relative, hash-verified; for future AI_Video_Editor import | `_bin_finder_handoff.json` |
| Tạo gói AI_Video_Editor (default off) | `ai_video_editor_bin_finder_adapter_v1` — historical compatibility adapter | `_ai_video_editor_bin_finder_adapter.json`, `_bin_finder_acceptance.json` |

They are independent (all four combinations work), neither implies the other, the
portable package does not require the legacy adapter, and neither schema changed.
Tooltips state the distinction.

## Default GUI export
```text
library/
  footage/scene_001.mp4 ...
  footage_manifest.json
  footage_index.csv
  _bin_finder_handoff.json
```
It verifies with `verify_handoff_package()` and remains valid after the folder is moved
or renamed.

## Unchanged
F017 schema/verifier, F015 staging/publish, F016 recovery, F019 production long-form
acceptance, F018 planning, F014 human approval, F006 clip duration, rotation/overlap/score
rules. One existing F015 GUI test now expects the new default status text.

## Limitations
AI_Video_Editor consumer integration is still **not** implemented; F020 only makes the
production GUI produce the portable package. The handoff choice is not persisted across
restarts (checkbox resets to checked).

Tests: `tests/test_gui_portable_handoff_f020.py`.
