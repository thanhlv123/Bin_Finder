# F012 — Authorized Media Acquisition & Local Cache

Discovery != acquisition.
Acquisition != verification.
Acquisition != editor-ready approval.

## Architecture and authorization

F011 Pexels/Pixabay search still uses the existing provider registry and
DiscoveryService. Search never invokes acquisition. No scraping, alternative
search, YouTube download or Storyblocks download is added.

`acquisition.AcquisitionService.acquire(AcquisitionRequest(...))` requires both
an existing F009 `ReviewDecision` with `accepted` and `user_authorized=True`.
Scene ID, candidate ID, provider and stable source ID must match the review.
Callers must supply the current review from their ReviewStore, as the GUI does;
the service is not an authentication system or a license authority. Cached
items require the same authorization. Missing identity, unusable media URL,
unsupported providers and non-HTTP(S) schemes are rejected before network IO.

The GUI uses the existing review panel: choose a candidate, then explicitly click
**Tải footage đã duyệt**. Approval alone does not download. **Hủy tải** requests
cooperative cancellation. A small AcquisitionWorker runs network, hashing and
file IO on a QThread; queued signals update status on the GUI thread. Known
length progress is bounded to 0–100%; unknown length shows `Đang tải…`.
Closing while downloading requests cancellation and leaves the window open
until completion; close again afterwards. In-flight search also defers close.
Results remain available in `MainWindow.acquired_assets` and on the currently
reviewed candidate, without changing selected clips or project readiness.

## Streaming, storage and cache

The default cache is `%LOCALAPPDATA%\BinFinder\cache\media`, following the
existing analysis cache convention. Without LOCALAPPDATA the fallback is
`~/.bin_finder/cache/media`, outside source directories. Callers can supply
`cache_root`; never use a tracked source directory. Existing `cache/` ignore
rules apply to repository test caches. No media payload is checked in.

Cache keys are SHA-256 of the format version, provider, stable source ID and
exact selected rendition/preview URL. Titles never affect identity. Signed URL
changes intentionally create a new identity. Each entry contains `media.mp4`
and `manifest.json`. Downloads use unique `.partial-*` staging directories,
256 KiB reads, a `media.part` file, fsync, and atomic manifest replacement.
The complete directory is renamed into its deterministic destination only
after validation. Existing destinations are never replaced. Concurrent
publication may fail one request safely; retry then obtains the cache hit.

Default limits are **1 GiB per file**, a **20-second socket timeout**, and a
**300-second elapsed deadline**, checked between reads. Constructor options
`max_bytes`, `timeout` (up to 60 seconds) and `deadline` (up to 3600 seconds)
configure them. There is no aggregate cache quota or automatic eviction.
Socket timeout bounds stalled operations; cancellation/deadline checks occur
between reads, so an in-flight operation must finish or time out first.

Cache hits perform no network request and re-read the manifest, regular-file
status, nonzero size, byte limit and full SHA-256. Corrupted, incomplete,
symlinked or unrelated entries fail closed and are retained for inspection.
Remove an invalid entry deliberately before retrying; acquisition never
silently overwrites it. This cache assumes an application-controlled local
directory, not storage writable by hostile concurrent processes.

## Manifest and validation

`bin_finder_acquisition_v1` records cache key/version, provider/source ID,
safe source page URL, creator, rights label, normalized allowlisted license
and creator metadata, rendition URL hash, width/height, resolution, known
duration, absolute local path, size, byte limit, SHA-256, UTC acquisition
timestamp and `usage_authorization=user_authorized_acquisition`.
That authorization describes the download request, not copyright permission.
Original provider usage authorization remains evidence, separately recorded
in safe source metadata. Rendition URLs are represented by a one-way hash;
source/license/creator URLs omit query strings and fragments. Raw provider
responses, request headers and arbitrary metadata are never persisted.

Validation requires a nonempty regular file within limits, matching received
Content-Length where supplied, an MP4 `ftyp` header and matching checksum/size.
Video/mp4 and binary MIME types are accepted. The existing FFprobeMediaProbe
additionally requires usable duration and dimensions when ffprobe is available.
No new executable or runtime dependency is installed. Without ffprobe,
container-header and integrity checks do not establish full decodability.

HTTP errors, timeouts, truncated responses, invalid content, size overflow,
probe errors, write errors and cancellation discard staging files and publish
no valid entry. One item never modifies another item's entry. Cleanup is
best effort if the OS itself prevents deletion. No response bodies, full
request URLs, API headers or exception details appear in errors. Known
BIN_FINDER key/secret environment values are redacted from persisted text.
Transport sends only User-Agent and Accept-Encoding, and validates redirects
as HTTP(S) without URL user information.

## Relationship to F003–F011

`CandidateRecord.acquisition_manifest` is an optional, backward-compatible
reference, leaving provider/source/scene/candidate identity intact.
`verified_candidate_path()` validates this reference against the candidate and
local bytes. CandidateAnalysisService admits remote-origin media only through
that validated reference. An unacquired remote URL remains ineligible even if
its preview string names a local file. Existing local-library behavior remains.

The resulting F003 CandidateAnalysis uses the actual local path and existing
analysis cache. F004 segment retrieval, F005 verification/VLM, F006 planning
and extraction, F007 indexing, F008 rotation/overlap, F009 review and F010
handoff retain their contracts. Callers explicitly analyze acquired candidates
and carry original provenance into reviewed SelectedClipRecords. Downloading
creates neither a SelectedClipRecord nor a successful AcceptanceReport.
Automatic analysis/rendering and a redesign of the prototype GUI are outside
this milestone. File integrity verification here is distinct from F005 semantic
verification and human approval of the resulting clip.

## Offline acceptance

No network or credentials are required:

```powershell
$f012Tests = @(Get-ChildItem tests/test_*f012*.py | ForEach-Object { $_.FullName })
.\.venv\Scripts\python.exe -m pytest -q $f012Tests --basetemp="D:\YouTubeTools\Bin_Finder\pytest_tmp"
.\.venv\Scripts\python.exe -m pytest -q --basetemp="D:\YouTubeTools\Bin_Finder\pytest_tmp"
git diff --check
```

## Explicit live acceptance

Configure existing local Pexels/Pixabay credentials, then explicitly authorize
the bounded test download:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m bin_finder.acquisition_smoke --approve-test-download
```

Without the flag every provider reports `SKIPPED_NOT_APPROVED`, without loading
credentials or accessing the network. With the flag, missing credentials report
`SKIPPED_NO_CREDENTIAL`. Each configured provider uses DiscoveryService for one
page of `ocean` results and acquires at most one item, with a 256 MiB cap,
15-second socket timeout and 120-second download deadline. The explicit flag
authorizes an acceptance-only accepted ReviewDecision, never a production
project review change. Media and safe manifests live in an OS temporary
directory outside tracked source and are removed afterwards. The command
verifies the file/manifest/checksum and a second acquisition's cache hit,
reporting `PASS` or `FAIL` separately per provider. Empty search or failed media
validation is FAIL. It never renders or exports. Ordinary pytest never runs
this live path against providers. Live acceptance must be reported separately
from offline acceptance.
