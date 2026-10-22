# F016 — Session Persistence & Recovery

Status: implementation in progress. The accepted seven-panel GUI remains unchanged.

## Phase 1: strict scene and UI snapshots

The new `session_codec` validates a versioned, allowlisted scene and UI
snapshot. The new `session_store` stores it in a per-project SHA-256-named
file under `%LOCALAPPDATA%/BinFinder/sessions` (or
`~/.bin_finder/sessions` when LOCALAPPDATA is absent). A small active
pointer tracks the last saved project. Writes use a temporary file, flush,
fsync, and atomic replacement. The format rejects unknown keys, duplicate
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
become unresolved with a reason, never silently reapproved. Remote-origin
selections are unresolved until their original F012 acquisition authorization
can be independently verified; a hash alone is not sufficient. F010/F015 gates
must still be recomputed by the GUI; persistence never stores READY.

## Remaining acceptance work

- Integrate the validated restoration result with GUI scene/filmstrip state.
- Add independent F012 authorization evidence for remote-origin selections.
- Add minimal workflow reference persistence without storing provider data.
- Connect GUI save/restore on project lifecycle without changing panel geometry.
- Recompute F010 readiness after restore; retain F015 READY-only export.
- Run full Windows CI and security review before PR/merge.
