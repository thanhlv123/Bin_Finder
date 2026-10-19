# F002 — Provider architecture and real discovery

F002 replaces the demo result generator with provider-backed discovery while keeping the accepted F001.5 layout fixed.

## Active provider adapters

- YouTube Data API v3 — discovery and metadata only. No general downloader is implemented.
- Storyblocks API v2 — search adapter only; requires valid API/project/user credentials and licensed use.
- Pexels Video API — stock video discovery.
- Pixabay Video API — stock video discovery.
- Local library — filename/path lexical discovery over user-owned/authorized files.

The **Báo điện tử** checkbox stays visible but is intentionally deferred. Selecting it produces a non-fatal notice instead of making a network request.

## Search flow

SceneRecord -> deterministic queries -> enabled providers -> normalized CandidateRecord -> metadata ranking -> 3-column result grid -> review panel.

Network discovery runs in a QThread, so the GUI remains responsive. Results from an older scene are ignored after the user changes scenes.

F002 scoring is metadata relevance only. It is not proof that the actual visual content matches the script. Actual clip analysis, transcript/time-range narrowing, scene segmentation, embeddings, and VLM verification are later milestones.

## Provider configuration

Secrets are loaded in this order:

1. Environment variable.
2. config/providers.local.json (gitignored).

Use config/providers.example.json as the template. Supported environment variables:

- BIN_FINDER_YOUTUBE_API_KEY
- BIN_FINDER_PEXELS_API_KEY
- BIN_FINDER_PIXABAY_API_KEY
- BIN_FINDER_STORYBLOCKS_PUBLIC_KEY
- BIN_FINDER_STORYBLOCKS_SECRET_KEY
- BIN_FINDER_STORYBLOCKS_PROJECT_ID
- BIN_FINDER_STORYBLOCKS_USER_ID
- BIN_FINDER_LOCAL_LIBRARY

No secret is written to candidate records, manifests, provider notices, or logs.

## Rights boundary

Discovery is not acquisition authorization. YouTube is discovery-only in F002. Storyblocks results require the user's valid license/access. Local files are marked for rights review unless the user knows they own or are authorized to use them.
