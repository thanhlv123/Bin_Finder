# BF-S06 — YouTube reference discovery + 1–7s licensed LOCAL footage cuts

**Research branch:** `research/bf-s06-youtube-shot-sourcing` stacked on `research/bf-s04a2-editorial-quality-gate` (Draft PR #39). No production GUI or `main` edits. Do not merge before local acceptance.

## What actually existed already

Bin Finder **already had** `src/bin_finder/providers/youtube.py` integrated with `providers/registry.py` and a configurable `BIN_FINDER_YOUTUBE_API_KEY`; it performs Google YouTube Data API `search.list` then `videos.list` metadata retrieval. This provider returns **watch URLs and thumbnails**, **not downloadable files**.

The BF-S02 single-slot research pilot restricted itself to Pexels, Pixabay, or local stock, and the F012 acquisition service intentionally only permits Pexels/Pixabay. The separate BF-S04A editorial shot planner was not wired to the YouTube reference provider and legacy ClipPolicy typically uses 3.5–7 seconds by default. No generalized automated YouTube video segmentation was previously demonstrated.

**YouTube Data API restrictions:** per the official [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies), Section III.E.1, API clients must not download/import/cache/store copies of YouTube audiovisual content without YouTube's prior written approval; API search's `videoLicense=creativeCommon` is a **discovery filter only**, not proof of transferable clip rights nor a direct downloadable-video license. YouTube Terms also restrict copying/download use to expressly authorized uses. A short 1–7-second cut does **not** inherently exempt copyright licensing. No `yt-dlp`, scraping, YouTube file import, YouTube AV downloading or API video playback interception is added.

## Research part A: YouTube metadata search per EditorialShot

`src/bin_finder/search/youtube_shot_discovery.py`:
- consumes validated, human-review-only BF-S04A `EditorialShot`;
- sends no request by default; requires explicit `approve_youtube_api_search=True`;
- uses existing `YouTubeProvider` and configured API key, at most **3 shot search queries**, max 10 refs, deduplicates valid eleven-character video IDs;
- defaults to CC metadata filter for finding possible reuse candidates, but user can include standard license **reference-only** results. YouTube labels never imply cutting/downloading is authorized;
- returns title/channel/description/duration, canonical watch URL/thumbnail, metadata license hint, and `manual-verification-required`/`acquisition_allowed=False`/`clip_export_allowed=False`;
- `search_attempts` counts high-level searches, **not** actual HTTP requests, because the existing YouTube provider uses two YouTube Data API endpoints per search; `api_http_requests_confirmed="unknown"`; no output file download.
- `src/bin_finder/search/youtube_shot_smoke.py` is the single-slot Gaspard/Savoie pilot. Without `--approve-youtube-api-search` it does not read private provider credentials, JSON or contact Google. It may use local config JSON if requested and a consented query executes.

### Local PowerShell metadata trial

```powershell
$repo = 'D:\YouTubeTools\Bin_Finder\Bin_Finder'
$lab = 'D:\YouTubeTools\Bin_Finder_BFS06_Research'
$env:PYTHONPATH = "$lab\src"
$py = "$repo\.venv\Scripts\python.exe"
$plan = 'C:\Users\pc\Desktop\BFS04A1R2_AI_Shot_Slot2.json'
& $py -m bin_finder.search.youtube_shot_smoke --plan-json $plan --project-root $repo
# No network in command above. Only with explicit user approval:
& $py -m bin_finder.search.youtube_shot_smoke --plan-json $plan --project-root $repo --approve-youtube-api-search --max-queries 1 --max-results 5
```

If no YouTube API key, it returns `youtube-api-key-not-configured`, and makes zero YouTube searches. Never paste API keys in messages or screenshots; configuration stays in local environment or gitignored `config/providers.local.json`.

## Research part B: clip / still from *independently supplied local* master

`src/bin_finder/search/authorized_local_cut.py`:
- only accepts real local `.mp4/.mov/.mkv/.m4v` source paths inside a user-selected allowed root; output path must be under a separately selected output root; rejects links/out-of-root, wrong extension, existing destination and remote/YouTube URL sources;
- explicit `provenance=user_owned_original_master` or `licensed_independent_master_copy`, affirmative `confirm_usage_rights=True` and `approve_local_cut=True` before any FFprobe or FFmpeg invocation. These are user declarations, not documentary license verification;
- FFprobe confirms source video stream/duration. The chosen window must be **1 to 7 seconds**, finite, start >=0, fully inside source;
- `--mode clip` uses existing `FfmpegClipExtractor` to create **new MP4**, no overwrite; `--mode still` extracts one JPG representative frame at the *middle* of the chosen window, to be **held by a later timeline for 1–7 seconds**. A JPEG itself has no duration;
- no YouTube media downloading, no YouTube API request, no cloud frames, no automatic semantic time-window selection, no changes to timeline or GUI. The selection of start/end is **manual** in this phase; automated temporal localization on a verified locally available media master is a future BF-S06B goal.
- no extraction from an arbitrary video found on YouTube merely because that video is public or labelled Creative Commons. The actual master must be delivered independently with adequate permission, or be user-owned original footage.

### Local Windows export after human rights approval

```powershell
$repo = 'D:\YouTubeTools\Bin_Finder\Bin_Finder'
$lab = 'D:\YouTubeTools\Bin_Finder_BFS06_Research'
$env:PYTHONPATH = "$lab\src"
$py = "$repo\.venv\Scripts\python.exe"
$srcroot = 'D:\Your_Licensed_Source_Videos'
$outroot = 'D:\Your_Approved_Clips'
# Both roots must exist. The source must be independently licensed;
# the file path here is an EXAMPLE to replace with the actual master file.
& $py -m bin_finder.search.authorized_local_cut_smoke `
  --source-path "$srcroot\my_licensed_original.mp4" `
  --source-root $srcroot `
  --output-path "$outroot\shot_001.mp4" `
  --output-root $outroot `
  --start 8 --duration 4 `
  --mode clip `
  --provenance licensed_independent_master_copy
# Dry run prints approval-required, creates NO media. To cut, the
# operator must separately append BOTH explicit consent switches:
# --confirm-usage-rights --approve-local-cut
```

Images: specify `--mode still` and `--output-path shot_001.jpg`. The `--duration` denotes a proposed 1–7s display hold, not a movie/video segment.

## Scope boundaries / future steps

- **Implemented:** official API metadata search by shot, watch URLs, human rights review status; 1–7s local video extraction and single still.
- **Not implemented:** streaming/disassembling YouTube-hosted audiovisual data, `yt-dlp` integration, automatic exact second detection inside YouTube videos, speech-to-video or temporal Vision grounding of YouTube-hosted content, external license verifications, automatic rights approvals, background crawls, production GUI, full script-to-timeline.
- **Next BF-S06B:** only for local authorized source masters, make a bounded frame-sample/ASR/temporal segment locator with human playback; generate top proposed 1–7s windows, then export those the user approves.
- **Next BF-S06C:** optionally extend the existing GUI to display candidate watch links, license/provenance labels and user-approved local media pairing after independent testing and YouTube-compliant playback.
- **Important:** YouTube reference discovery improves candidate recall, but does **not** automatically increase the number of actually licensed, cuttable media files. Continue Pexels/Pixabay as ready-to-use asset sources.

## Tests

`tests/test_bf_s06_youtube_shot_sourcing.py` — no API calls without opt-in, two-API-metadata-requests per `YouTubeProvider.search` action, candidate dedup, CC vs standard metadata, no AV acquisition, bounded query budgets, disallowed graphic shots, local cut permission/time/file-system constraints, no source path escaping and disabled overwrite.

CI: isolated `bf-s06-research-windows.yml`, full Windows project tests with real FFmpeg export and GUI regression tests. No real YouTube API calls in CI; metadata is mocked.
