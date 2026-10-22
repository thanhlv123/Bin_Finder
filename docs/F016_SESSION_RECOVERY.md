# F016 — Session Persistence & Recovery

Status: implementation in progress. The accepted seven-panel GUI remains unchanged.

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
become unresolved with a reason, never silently reapproved. Remote-origin
selections are unresolved until their original F012 acquisition authorization
can be independently verified; a hash alone is not sufficient. F010/F015 gates
must still be recomputed by the GUI; persistence never stores READY.

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

## Remaining acceptance work

- Add independent F012 authorization evidence for remote-origin selections.
- Add minimal workflow reference persistence without storing provider data.
- Run full Windows CI and security review before PR/merge.
