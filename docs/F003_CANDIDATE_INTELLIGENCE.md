# F003 — Candidate Intelligence

F003 adds the local/authorized-media analysis foundation required by later semantic and VLM milestones. It does **not** redesign the accepted F001.5/F002 GUI.

## What is implemented

- Full SHA-256 content fingerprinting for stable media identity.
- FFprobe metadata adapter: duration, resolution, FPS, codec, audio presence.
- SRT/VTT sidecar transcript parsing with timestamps.
- Shot-boundary abstraction with an FFmpeg scene-change backend.
- Safe single-shot fallback when FFmpeg is unavailable or scene detection fails.
- SQLite analysis cache keyed by `sha256 + analyzer_version`.
- Content-based cache reuse even when a file is renamed or moved.
- CandidateAnalysisService for local/authorized files.

## Why FFmpeg is used in F003

The repository engineering rules require approval before adding a new runtime Python dependency. F003 therefore implements shot-boundary detection through the existing FFmpeg runtime instead of adding PySceneDetect as a dependency.

The detector is isolated behind a small interface. A PySceneDetect backend can be added later without changing search, cache, or GUI contracts.

## Rights boundary

F003 does not add a remote downloader. YouTube remains discovery/metadata only. Analysis is applied to local files or other media the user is authorized to process.

## Cache behavior

The cache stores analysis data only:

- content SHA-256
- technical metadata
- transcript segments
- shot boundaries
- analyzer version
- warnings

It does not store provider credentials, API keys, signed URLs, or tokens.

## Next milestone

F004 will add hybrid retrieval over analyzed segments: exact/keyword ranking + transcript relevance + visual/semantic provider interfaces, while keeping the GUI layout fixed.
