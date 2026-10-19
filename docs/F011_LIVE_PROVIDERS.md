# F011 — Live Provider Integration

Extends the F002 adapters, registry, configuration and stdlib HTTP client. No
runtime dependencies or alternate search pipeline are introduced. The official
video endpoints remain:

- https://api.pexels.com/v1/videos/search
- https://pixabay.com/api/videos/

Configuration still uses `BIN_FINDER_PEXELS_API_KEY` and
`BIN_FINDER_PIXABAY_API_KEY`, with environment values taking precedence over
the gitignored `config/providers.local.json`. Copy only the existing placeholder
`config/providers.example.json`; never commit the local file. Config repr hides
credential fields.

Requests have a 15-second socket timeout, one page, no retries, and an 8 MiB
JSON response cap. Transport errors expose only safe diagnostics; provider
response bodies and request URLs are never used as error messages. A malformed
collection is a provider error; malformed individual records without stable IDs
are skipped. Missing optional fields remain empty or zero, and nonfinite or
negative numeric values normalize to zero.

Pexels chooses the highest-area usable MP4 (or unspecified-type) rendition,
breaking ties by URL and file ID. Pixabay chooses the first nonempty HTTP(S)
rendition in large/medium/small/tiny order. Candidate limits are applied even
when Pixabay's minimum page size is larger than the requested limit.

Normalized candidates retain source page, creator, thumbnail, preview URL,
provider-prefixed stable ID and allowlisted `source_metadata`: rendition
identifiers/URLs/dimensions, creator ID, provider license reference, and explicit
unknown usage authorization. These metadata are not a grant of acquisition
rights. Raw API responses and credentials are not persisted.

`source_metadata` is additive to CandidateRecord. SelectedClipRecord and
ReviewDecision gain optional provenance fields; the F010 v1 adapter exports
these fields alongside its existing footage fields. Callers constructing an
approved SelectedClipRecord must copy source_url, creator and source_metadata
from the reviewed candidate. Ranking uses dataclass replacement and preserves
metadata. Acquisition, analysis of authorized local media, verification,
diversity rules, review decisions and readiness gates remain separate.

The existing SearchWorker/QThread delivers candidates to the same GUI grid and
review panel. Creator/source-page tooltips supplement the existing duration,
resolution, provider and score. Existing generated thumbnail placeholders and
preview behavior remain; this milestone does not add a remote media player or
automatic acquisition. The provider protocol has no cancellation token; an
in-flight request finishes or times out. No layout changes are made.

## Offline verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_live_providers_f011.py --basetemp="D:\YouTubeTools\Bin_Finder\pytest_tmp"
.\.venv\Scripts\python.exe -m pytest -q --basetemp="D:\YouTubeTools\Bin_Finder\pytest_tmp"
```

## Explicit live acceptance

Ordinary pytest never calls a real API. To opt in, configure credentials locally
and run from the repository root:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m bin_finder.provider_smoke --script "D:\scripts\CUBA_VIDEO_001.txt"
```

The command reports each provider separately. Missing credentials are
`SKIPPED_NO_CREDENTIAL`. Each configured provider searches `ocean` once, then
the existing DiscoveryService searches the first three script scenes (at most
eight total API calls). No files or API responses are saved. Empty live results
are reported as FAIL rather than claiming successful acceptance. Omitting a
script when keys are configured reports real-script search FAIL. Script splitting
matches the GUI sentence splitter. No real CUBA script asset is checked in;
F010's CUBA_VIDEO_001 project is a synthetic adapter test fixture.

Live search is discovery acceptance only. Human approval, authorized local
acquisition/extraction, source-diversity validation and F010 project readiness
are still required before an editor-ready handoff.

References: [Pexels API](https://www.pexels.com/api/documentation/),
[Pixabay API](https://pixabay.com/api/docs/).
