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

## Remaining acceptance work

- Implement allowlisted final clip evidence and SHA-256 revalidation.
- Restore invalid or missing media as unresolved scenes.
- Add minimal workflow reference persistence without storing provider data.
- Connect GUI save/restore on project lifecycle without changing panel geometry.
- Recompute F010 readiness after restore; retain F015 READY-only export.
- Run full Windows CI and security review before PR/merge.
