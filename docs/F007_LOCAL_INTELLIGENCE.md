# F007 — Local Footage Intelligence

F007 makes the existing **Thư viện local** source incremental and local-first without changing the accepted GUI layout.

## Incremental index

Each configured local library gets its own SQLite index under the Bin Finder cache area. A scan compares file path, size, and modification time before calculating SHA-256.

- unchanged media is not re-hashed;
- changed/new media is hashed and refreshed;
- transcript sidecar changes refresh transcript text without re-hashing unchanged video bytes;
- deleted files are removed;
- renames keep the same content-based source identity.

Source IDs use the first 16 hex characters of SHA-256, so a rename does not create a new logical source.

## Local-first discovery

When **Thư viện local** is enabled, Bin Finder searches it before network providers. If the best local result reaches the default acceptance threshold of 0.88, network discovery is skipped for that scene. Otherwise YouTube / Storyblocks / Pexels / Pixabay continue normally.

This behavior lives in the search service; no new GUI control or layout change is required.

## Search by image

The local provider exposes a search-by-image API. F007 uses a dependency-free 64-bit perceptual frame hash extracted through FFmpeg. Video hashes are computed lazily the first time image search is used and then cached in SQLite.

This is a visual-near-duplicate / appearance similarity baseline, **not** semantic CLIP search. The API boundary is ready for a future embedding provider without changing the local index contract.

## Rights boundary

Only local files configured by the user are indexed. F007 does not add a remote downloader.
