# F015 — Final Footage Export Library

F015 materializes explicit F014 final selections into a clean local footage
library. It renders no final video, invokes no AI_Video_Editor process, and adds
no runtime dependency or provider/network operation.

## Authorization and coordinate contract

`FinalExportService.export(project_id, scenes, selections, destination, options,
progress, cancelled)` is pure Python. It reuses `build_final_project()` and calls
`evaluate_project()` on the **original source-coordinate selections**. Only a
READY report authorizes export; a blocked result returns `not_ready` with the
structured F010 report, without creating directories or extracting clips.
F010's duration, quality, coverage, source rotation and overlap gates are unchanged.
Becoming READY never starts an export automatically.

The original report stays authoritative throughout the run. When explicitly
requested, an adapter-only materialized `FootageProject` preserves logical clip
and provider/source identity but references the extracted files with local
`start=0`, `end=duration`. These are coordinates inside independent trimmed files.
F015 does **not** run source overlap evaluation on those local coordinates.

Before `write_integration_package(stage, materialized_project, original_report)`,
F015 checks matching project ID, scene IDs/order, selected count, clip IDs,
provider/source identity, scores, per-clip and total durations, normalized ranges,
and nonempty regular staged files corresponding to final paths. It uses no
incomplete override. The adapter remains `ai_video_editor_bin_finder_adapter_v1`;
its acceptance JSON contains the original READY report.

The A–B–A regression uses original ranges A 10–15, B 0–5, A 30–35, while all three
adapter ranges are 0–5. Both occurrences of A retain `source_id=A`. No F010 public
contract, `SelectedClipRecord` fields, or adapter v1 schema is changed.

## Extraction and source integrity

Every extraction uses an accepted `ClipProposal` and the existing
`FfmpegClipExtractor`, with `overwrite=False`. There is no new FFmpeg command
builder or shell invocation. Sources must be regular local files; symlinks and
Windows junctions in the path are rejected. Finite, nonnegative, correctly ordered
timestamps must match duration and the existing F006 3.5–7 second policy. Scores
must be finite normalized values.

Current source SHA-256 must match approved `source_metadata.media_sha256` when
present. A second hash after extraction detects modification during the bounded
operation. F015 never updates approved identity or writes the source file.

Outputs must be nonempty regular files at the expected paths with matching
extractor byte counts and durations. When configured or available through PATH,
the existing `FFprobeMediaProbe` additionally checks video presence and duration
within 0.25 seconds. With no FFprobe, validation relies on F006's returned duration
and file checks; it does not claim an independent measurement of duration.

## Layout, staging and overwrite policy

The selected output folder is the completed library:

```text
library/
  footage/
    scene_001.mp4
    scene_002.mp4
    scene_003.mp4
  footage_manifest.json
  footage_index.csv                         # optional
  _ai_video_editor_bin_finder_adapter.json  # explicit option only
  _bin_finder_acceptance.json               # with adapter only
```

Clips are ordered by script scene order. Safe stable scene IDs supply filenames
by default; unsafe IDs and Windows reserved names use `scene_NNN.mp4`. Disabling
scene-ID naming always uses the ordered `scene_NNN.mp4` form. Case-insensitive
collisions fail closed. Remote titles never determine filenames.

A unique `.bin-finder-export-partial-*` directory is created beside the requested
library, on the same filesystem. All extraction and metadata writes happen there.
Only after every required operation succeeds is the directory renamed to the
final destination. Final absolute paths in the staged adapter become valid at
publication. Metadata or adapter failure prevents publication too.

An existing empty output folder is supported; a nonempty directory, existing
file, linked destination or output inside this source repository is rejected.
There is no silent overwrite, retry loop, automatic versioning or overwrite
option. Failed/cancelled staging is removed where filesystem access permits.
Publication is a Windows directory rename, not a power-loss recovery protocol;
unrecoverable filesystem/permission errors can leave an explicitly partial
staging directory for manual cleanup.

## Manifest, CSV and provenance

`footage_manifest.json` is mandatory and versioned as
`bin_finder_final_export_v1`. It includes UTC export time, project ID, original
readiness report, scene/selection/export counts and total selected duration.
Each scene entry links its scene ID/order and clip ID to its exported relative
path and filename, provider/source ID, duration, semantic/VLM/final scores,
rights status and creator. Traceability fields are:

- `original_source_start_seconds` / `original_source_end_seconds`
- `original_source_media_sha256`
- `exported_file_sha256`

Optional extended metadata uses F012's provenance allowlist and known credential
redaction; URL queries/fragments are removed. Arbitrary provider responses,
Authorization headers, provider credentials and unsafe metadata are not copied.
Materialized source metadata also includes explicitly named `f015_*` original
range/hash fields and a materialized flag.

The stdlib CSV writer creates optional `footage_index.csv`, one row per scene in
script order: scene order/ID, clip ID, filename, provider, source ID, duration,
final score, rights status and creator. Disabling extended metadata retains the
required manifest identity/score/rights fields and omits the extended provenance.

## GUI and cancellation

Panel 7 retains the seven-panel workspace and authoritative output-folder selector.
“Xuất footage đã chọn” is gated by F010 READY and disabled while an export runs.
Timestamp extraction and the completion manifest are checked and disabled because
they are mandatory. Scene-ID names, CSV and extended metadata use the existing
checkboxes; a separate unchecked adapter option explicitly requests the existing
F010 package after extraction.

`FinalExportWorker` runs hashing/extraction and metadata writes on a `QThread`.
Queued signals update GUI progress counts, current scene and success/failure/
cancellation status. “Hủy” requests cooperative interruption. Closing while an
export runs requests cancellation and defers closing until the worker finishes.
Workers retain the project/options snapshot captured at the explicit click.

Cancellation checks occur before every extraction, after extraction validation,
and before publication. The current bounded F006 subprocess finishes normally;
no unsafe FFmpeg kill is used. Further clips are not scheduled, incomplete output
is not published, and staging is cleaned where safe.

## Offline verification and real FFmpeg acceptance

Tests use fixture media/output exclusively in the external pytest temp directory:

```powershell
$f015Tests = @(Get-ChildItem tests/test_*f015*.py | ForEach-Object { $_.FullName })
.\.venv\Scripts\python.exe -m pytest -q $f015Tests --basetemp="D:\YouTubeTools\Bin_Finder\pytest_tmp"
.\.venv\Scripts\python.exe -m pytest -q --basetemp="D:\YouTubeTools\Bin_Finder\pytest_tmp"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m bin_finder.final_export_smoke --approve-test-export
git diff --check
```

Without the explicit flag the smoke prints `SKIPPED_NOT_APPROVED` and does no
work. It discovers FFmpeg through `FfmpegClipExtractor` (`BIN_FINDER_FFMPEG` or
PATH), prints `SKIPPED_NO_FFMPEG` with a failing acceptance exit code if unavailable,
and uses bounded subprocesses. No executable path is hardcoded.

The approved smoke generates small synthetic sources outside the repository,
exports a three-scene READY A–B–A fixture, decodes each extracted MP4, verifies
manifest/hash/CSV linkage and optional adapter paths with normalized local ranges,
checks original range traceability and READY acceptance JSON, rejects a second
export to the same destination, and cleans all temporary files. It uses no
network, production media, API keys or database.

Verified acceptance: baseline **310 passed**; F015 focused **53 passed, 1 skipped**;
full regression **363 passed, 1 skipped**; real offline FFmpeg smoke **PASS**.
The skip is the Windows symlink creation test when privilege/Developer Mode is
unavailable. The real smoke includes the original-coordinate A–B–A / local-coordinate
adapter regression and removes its temporary media and export library.

Limitations: selections remain session-only as in F014; hashing assumes
application-controlled storage and cannot defeat a hostile filesystem race.
Cancellation cannot interrupt the current bounded FFmpeg extraction. No project
rendering, provider acquisition, export resume, overwrite/version UI, VPS or
multi-user behavior is included.
