# F013 — Acquisition-to-Analysis Orchestration & Resume

Discovery != approval.
Approval != acquisition authorization.
Acquisition != analysis.
Analysis != verification.
Verification != editor-ready acceptance.
F013 does not automatically render/export.

## Architecture

`workflow.WorkflowService.run(WorkflowRequest(...), progress=..., cancelled=...)`
accepts scenes, candidates, current F009 review decisions and a separate boolean
`authorize_acquisition`. The core imports no Qt. Results contain ordered per-item
status, a categorized safe error, the original-provenance CandidateRecord with its
acquisition reference, verified local path, F003 CandidateAnalysis and downstream
contracts. `WorkflowResult.by_scene` groups those items without dropping failures.

Existing public APIs are reused:

- F012 `AcquisitionService.acquire(AcquisitionRequest(...))` and
  `verified_candidate_path()` own downloading, integrity, provenance and media cache.
- F003 `CandidateAnalysisService.analyze_candidate()` and `AnalysisCache` own
  probing, scene detection, transcript handling and content-based analysis cache.
- F009 `ReviewDecision.normalized()` validates current decisions supplied by the
  caller, normally from `ReviewStore.decisions()`. No review is written by F013.
- F004 `HybridRetrievalEngine.rank_analysis()` produces RankedSegments.
- Optional F005 `VerificationReranker.rerank()` and F006
  `SmartClipPlanner.propose_many()` retain their existing contracts.

Example (caller supplies current scenes/candidates/reviews):

```python
from bin_finder.workflow import WorkflowService, WorkflowRequest

service = WorkflowService(project_id="my-project")
request = WorkflowRequest(tuple(scenes), tuple(candidates), tuple(reviews),
                          authorize_acquisition=True)
report = service.run(request, progress=on_progress, cancelled=is_cancelled)
```

## Authorization and local eligibility

Every remote-origin item requires exactly one current accepted F009 decision for
its scene/candidate, with matching provider/source identity. F013 never restores
review acceptance from run state. Missing, rejected, waitlisted, ambiguous or
mismatched reviews stop that item. F012 independently checks authorization again
when called, including cache hits. The request authorizes acquisition only when
the value is literally `True`.

Without new authorization, verified acquired references can proceed to analysis;
remote-only candidates stop with `authorization_required` before acquisition.
An authorized remote-only candidate uses F012, including its verified cache path.
An invalid supplied/persisted acquisition reference fails closed, even if download
authorization is present. Remote URLs never enter analysis. Existing local-library
candidates use F003's local eligibility contract and must be regular local files.

Before and after analysis F013 checks byte identity. Remote media is revalidated
through F012; analysis must reference the same local path and SHA-256. Nonusable
video metadata fails with `unsupported_media`; F003 warnings alone are not proof
of successful video analysis. Provider/source/scene/candidate identity, creator,
source page URL and source_metadata survive in memory unchanged. Credentials and
arbitrary metadata are excluded from workflow persistence.

## Run state, resume and idempotency

`workflow.json` uses `bin_finder_workflow_v1`, UTC update timestamps and an `items`
mapping keyed by SHA-256 of scene/candidate/provider/source IDs. Each item records
those identifiers, a hashed source/rendition signature, stage, local path,
acquisition manifest reference, media SHA-256, F003 analysis cache key and optional
safe failure code/message. Titles never define identity. Stages are `pending`,
`acquiring`, `acquired`, `analyzing`, `analyzed`, `failed`, `cancelled`, `skipped`.

Writes use a unique temporary file in the work directory, flush/fsync and atomic
`os.replace`. A cooperative exclusive `workflow.lock` prevents concurrent writers
to the same run. After a process crash, confirm no worker remains before manually
removing an abandoned lock. A malformed root manifest fails run initialization;
an inconsistent item fails in isolation. Stale items remain quarantined with
`stale_state` until deliberately repaired/removed. No silent redownload repairs
corrupt F012 entries.

Resume revalidates identifiers, rendition/source signature, F012 manifest, bytes
and path. It restores acquired references even after analysis failure/cancellation.
It calls the same F003 analysis API again: unchanged bytes, transcript and analyzer
version hit the existing cache without probing/detection. Transcript/version
changes use F003's ordinary invalidation. F013 never serializes a second analysis
payload/cache format. Missing analysis cache entries are recomputed after media
validation. Retrieval and configured optional downstream work are recomputed.
Ordering is deterministic by scene order and stable IDs. No selection or review
records are created, so repeating work cannot duplicate them.

## Cancellation, progress and isolation

Progress events carry item index/count, scene/candidate IDs, stage and optional
bounded percent. Download percentage exists only for a known total. Acquisition
receives the cancellation callback. Checks between stages stop new scheduling;
remaining items receive cancelled results. Completed items from the current run
remain analyzed. F003 has no cancellation argument: its current bounded subprocess
must finish before cancellation is observed. Its cached result may be reusable,
but cancelled current work is not reported as analyzed. No threads/processes are
killed. Observer callback errors cannot invalidate completed media.

Transport, corrupt cache, analysis, unsupported media and stale reference failures
are per-item. Other items continue. Optional downstream failures retain successful
analysis and report a failed/incomplete stage. Failure strings never contain raw
exceptions. A state-write failure reports `state_write_failed`; if the disk cannot
write, the last atomic snapshot remains and the failed transition cannot be
promised durable. Unavailable run initialization is a safe WorkflowStateError.

## Storage and security

Default workflow storage is `%LOCALAPPDATA%\BinFinder\workflows\<project-hash>`;
fallback is `~/.bin_finder/workflows/<project-hash>`, never the current directory.
The default F003 cache used by this service is `analysis.sqlite3` inside that work
area. An explicit `work_dir` is supported; callers must choose application/project
storage outside tracked source. F012 media remains in F012's normal media cache
unless its existing constructor is explicitly configured. No media is copied by
F013. Tests use the prescribed external pytest temp directory.

Only references/IDs/hashes and categorized failures are persisted. No provider
API response, source/rendition URL, header, transcript, analysis warning or arbitrary
source_metadata enters workflow state. Known BIN_FINDER key/secret environment
values are redacted as defense in depth. F011/F012 credential/transport protections
are unchanged. Storage assumes an application-controlled directory, not hostile
concurrent filesystem modification; hashing is an integrity check, not licensing.

## GUI and downstream boundaries

The existing review area adds **Tải và phân tích tư liệu đã duyệt** (explicitly
authorizes acquisition for the current reviewed item) and **Hủy xử lý**. Network,
hashing, analysis and ranking run in WorkflowWorker, following existing QThread
signals. Result/progress signals reach GUI slots through queued Qt delivery.
The worker always delivers partial reports, plus a cancellation signal when needed.
Unexpected run initialization errors use a safe failure signal. Per-item failures
stay in the report. Results are held in `MainWindow.workflow_results`, keyed by
scene/candidate/provider/source. Existing search/review/download controls remain;
acquisition and workflow cannot run concurrently in the same window. Closing during
workflow requests interruption and defers close until the worker finishes.

F004 ranking runs locally. Verification is `not_configured` unless a reranker is
injected; fallback/low-confidence results remain incomplete and do not advance to
planning. Planning requires explicitly configured planner and actual verified
results. It creates proposals only, never extracts media. F007 LocalMediaIndex can
consume returned paths/analysis; automatic indexing is `not_configured`. F008
SourceDiversitySelector can consume original candidate identity and proposed
ranges; final diversity is `awaiting_final_selection`. F009 final review remains
`required`. F010 `evaluate_project`, `build_ai_video_editor_manifest` and
`write_integration_package` are unchanged: F013 creates no SelectedClipRecord,
AcceptanceReport or handoff files. Readiness remains `not_evaluated` and handoff
`not_requested`. An analyzed result is never editor-ready acceptance.

## Offline acceptance

No Internet or credentials required:

```powershell
$f013Tests = @(Get-ChildItem tests/test_*f013*.py | ForEach-Object { $_.FullName })
.\.venv\Scripts\python.exe -m pytest -q $f013Tests --basetemp="D:\YouTubeTools\Bin_Finder\pytest_tmp"
.\.venv\Scripts\python.exe -m pytest -q --basetemp="D:\YouTubeTools\Bin_Finder\pytest_tmp"
git diff --check
```

## Explicit live smoke

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m bin_finder.workflow_smoke --approve-test-acquisition
```

Without the flag each provider reports `SKIPPED_NOT_APPROVED` without loading
credentials or searching. With it, missing keys report `SKIPPED_NO_CREDENTIAL`.
Existing provider configuration searches one `ocean` query, selects at most one
candidate per Pexels/Pixabay, and creates an acceptance-only accepted ReviewDecision.
F012 limits each asset to 256 MiB, socket timeout 15 seconds and acquisition deadline
120 seconds. Existing F003 probe/detection subprocess timeouts bound analysis.
PASS requires real acquisition, verified local video analysis, persisted state and
successful resume/cache reuse. Failures report FAIL per provider with no exception
detail. Temporary media/run/analysis storage is outside source and removed on exit.
Ordinary pytest never invokes live acceptance; mock passes are not live PASS.
The command never renders, extracts or exports to AI_Video_Editor.

Limitations: no automatic stale-state repair, cache eviction, cross-project batch
scheduler or instant cancellation inside F003. Optional provider/model calls retain
their own timeouts. Explicit caller-provided directories must be chosen responsibly.
