# F016 — Session Persistence & Recovery

Status: **PASS**.
The accepted seven-panel GUI remains unchanged.

## Phase 1: strict scene and UI snapshots

The new `session_codec` validates a versioned, allowlisted scene and UI
snapshot. The new `session_store` stores it in a per-project SHA-256-named
file under `%LOCALAPPDATA%/BinFinder/sessions` (or
`~/.bin_finder/sessions` when LOCALAPPDATA is absent). A small active
pointer tracks the last saved project. Writes use a temporary file, flush,
fsync, and atomic replacement. The format rejects credential-like script, scene and UI values, including known provider environment secrets. It rejects unknown keys, duplicate
JSON keys, oversized data, nonfinite scene durations, linked paths and
unvalidated selection or workflow payloads.

This phase deliberately refuses to persist final clip selections or workflow
references until F014 source identity evidence can be revalidated on load.
No candidate approval is promoted into final approval, no READY flag is
serialized, and no provider response or downloaded media is stored.

## Phase 2: local final-approval recovery

F014 `SelectedClipRecord` values can now be converted to a strictly allowlisted
session representation. Only explicit final records are serialized; arbitrary
candidate/provider payloads, source URLs (including signed queries), and
unknown metadata keys are not persisted. The stored SHA-256 is mandatory.
`restore_session()` validates the snapshot, rejects linked/missing/empty files,
re-hashes local media and retains only exact identity matches. Invalid selections
become unresolved with a reason, never silently reapproved. Remote-origin selections require independent revalidation of the original
F012 app-local cache manifest: provider/source, cache directory, explicit
acquisition marker, rendition identity, size and SHA-256 must match. Signed
rendition URLs are never persisted. This uses F012's app-controlled cache
trust boundary, not a copyright license or new final approval. F010/F015
readiness is recomputed by the GUI and never persisted.

## Phase 3: GUI session lifecycle

The existing seven-panel GUI now loads the active session at startup and
restores script, scenes, current scene, export directory, and explicit F014
final selections only after the F016 local SHA-256/path revalidation. It
projects validated selections into the scene badges and filmstrip and
recomputes F010 readiness and F015 READY-only export from scratch.
Candidate review state and READY are never restored as approvals.

Script, output-directory, scene and final-approval changes are saved with
a short debounce. Closing flushes the session after active workers finish;
project-name changes save the previous project before clearing its approvals.
Unresolved selections remain stored as validated evidence (never as approved
GUI state), so closing and restarting does not erase the user's earlier choice.
A newly split script or changed project discards old unresolved references.
Corrupt/unsafe active snapshots are not overwritten by demo data on close.
Each test uses isolated local application data to prevent cross-test sessions.

## Phase 4: non-authoritative F013 workflow references

Completed F013 analysis items now persist only scene/candidate/provider/source IDs,
a workflow signature digest and a media SHA-256. References are accepted only
from the current project's existing F013 workflow state file. On restart the
state must still match, and its referenced local media must be regular,
non-linked and SHA-256-identical. Stale references are discarded. No state
paths, source URLs, candidate/provider payloads, acquired media, or workflow
objects enter the session snapshot. The GUI can display the count of recovered
historical references, but does not reconstruct runnable analysis results,
candidate approval, F012 acquisition authorization, final approval or READY.
Users explicitly rerun F013 to prepare clips; the original F013 resume checks
still apply. Re-splitting a script or changing project clears these references.

## Phase 5: path limits and end-to-end acceptance

Restore checks each media path with an explicit `lstat` instead of relying on
`Path.is_file()`, which hides some errors as "missing". When a filesystem check
fails with WinError 206 / `ENAMETOOLONG`, or fails for a Windows path at or over
MAX_PATH (260 characters), the selection becomes unresolved with reason
`local-media-path-too-long`. Paths are never truncated or shortened, the stored
evidence keeps the original path, and media is never treated as valid when the
check fails. F012's cache layout and acquisition contract are unchanged.

`bin_finder.session_export_smoke` chains, offline with real FFmpeg and synthetic
media in temporary storage outside the repository:

restore session -> revalidate final selections (SHA-256) -> F014
`build_final_project` -> F010 `evaluate_project` READY -> real F015 export.

It reuses the F015 A–B–A fixture: readiness and manifest provenance stay in
original source coordinates (10/0/30 s), while the materialized adapter uses
local 0 → 5 s ranges. It then replaces one source after the session was saved
and confirms that scene restores as `media-identity-changed`, READY is false and
F015 returns `not_ready` without creating a library. The pytest
`test_session_export_e2e_f016.py` runs the same chain plus a GUI restart that
exports through the existing Panel 7 worker; it skips when FFmpeg is absent.

```powershell
$f016Tests = @(Get-ChildItem tests/test_*f016*.py | ForEach-Object { $_.FullName })
.\.venv\Scripts\python.exe -m pytest -q $f016Tests --basetemp="..\pytest_tmp"
.\.venv\Scripts\python.exe -m pytest -q --basetemp="..\pytest_tmp"
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m bin_finder.session_export_smoke --approve-test-export
git diff --check
```

On this development machine the default pytest temp directory is not writable,
and deep `--basetemp` folders can exceed MAX_PATH for fixtures that create F012
cache paths, so use the short basetemp above (a sibling of the repository checkout).

Local acceptance (Windows 10, Python 3.12): F016 focused 41 passed, 2 skipped;
full regression 404 passed, 3 skipped; F016 restore/export smoke PASS; F015
smoke PASS. Skips are symlink-creation tests without Windows privilege.

## Acceptance

F016 is **PASS**. Verified acceptance:

- Windows CI (`windows-latest`, Python 3.12): **407 passed, 0 skipped, 0 failed**,
  including both `test_session_export_e2e_f016.py` tests (the workflow fails if
  they are skipped) and the symlink-refusal tests.
- CI installs the fixed Gyan FFmpeg 9.0.2 Windows essentials build as a CI test
  tool only and verifies its hardcoded SHA-256 before use. It is not an
  application runtime dependency.
- Real F015 FFmpeg smoke: `PASS_F015_REAL_FFMPEG`.
- Real F016 smoke: `PASS_F016_RESTORE_EXPORT` (restore -> SHA-256 revalidation
  -> F010 READY -> F015 export; tampered source unresolved / `not_ready`).
- MAX_PATH / WinError 206 restore fails closed as `local-media-path-too-long`.
- Remote F012 cache provenance is revalidated before a remote selection restores.
- F013 workflow references restore as non-authoritative hints only.
- The GUI lifecycle restores validated state only.
- READY is never persisted; F010/F015 readiness is always recomputed.
- Security/artifact review: no credentials, signed URL queries, raw provider
  responses, developer-machine paths, media, manifests, caches, databases, logs
  or binaries in the change set. F010/F014/F015 contracts are unchanged.
