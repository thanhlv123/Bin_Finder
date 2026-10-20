# F014 — Workflow Review & Final Selection Integration

Candidate approval != final clip approval. F009 `accepted` authorizes review for
acquisition/analysis; it never creates final footage or editor readiness.

## Core and preparation

`final_selection.FinalSelectionService` is pure Python. `prepare(scene, item)` is
an explicit F014 final-review preparation step, separate from F013 defaults.
It reuses existing verified segments/proposals. When verification was
`not_configured`, ranked segments can pass through `VerificationReranker` with
`HeuristicContextVerifier`, followed by `SmartClipPlanner`. Rejected proposals or
failed/fallback verification are never repaired into accepted options implicitly.
The heuristic is transcript/metadata evidence, not a claim that a VLM inspected frames.

Review options are evidence descriptions, not SelectedClipRecords. Only an
explicit approval constructs a final record. `options(scene, item)` requires analyzed status, usable video metadata, a regular
local media file, matching analysis path and current SHA-256. Remote-origin files
must also pass F012 `verified_candidate_path()`. Remote URLs, acquisition alone,
analysis alone and CandidateRecord proposed ranges are insufficient.

Every option requires an accepted F006 ClipProposal, exactly matching F004 ranking
and F005 verification unit evidence, verified status and verification result,
matching local paths, finite timestamps inside the ranked unit/media duration,
and the existing 3.5–7.0 second ClipPolicy. Missing or invalid evidence fails closed.

## Scores, identity and diversity

SelectedClipRecord semantic_score comes from RankedSegment.scores.final;
vlm_score comes from matching VerifiedSegment.verification_score (including an
identified heuristic verifier); final_score comes from VerifiedSegment.final_score.
Missing scores produce no option. CandidateRecord.score is never substituted.
Finite normalized scores are required rather than inventing a confidence value.

clip_id is SHA-256 of scene/candidate/provider/source IDs, media content hash,
proposal unit_id and start/end. Repeated identical approval reuses the same logical
clip. Scene ID stays stable when footage changes. `approve(...,
human_approved=True)` returns an ApprovalResult with a complete ordered selection
snapshot. The boolean must literally be True. One record replaces that scene's
previous record only after all gates pass; any failure returns previous selections.

F008 SourceDiversitySelector/DiversityCandidate validate the entire proposed set.
Only the actual human choices are offered; F008 cannot substitute another scene's
approved clip. Cooldown/anti-adjacency, same-source overlap, duplicate groups and
quality-drop guardrails remain active. A-B-A is permitted with disjoint A ranges.
The chosen option must also stay within F008's quality-drop floor relative to the
best eligible option. A conflict blocks the new approval, preserving all previous
choices. SelectionDecision now adds optional conflict_reasons diagnostics without
changing existing selection behavior or required constructor arguments.

## Project readiness and explicit handoff

`build_final_project(project_id, scenes, selections, output_dir)` accepts only
SelectedClipRecords, validates scene linkage/uniqueness, and sorts by script order.
Preliminary CandidateRecords cannot become a project selection through this API.
`evaluate_project()` remains the authoritative F010 gate: missing scenes, low final
scores, source rotation, overlap and expected script duration are reported separately.
The default 60–180 second policy is unchanged. Only AcceptanceReport.ready means READY.

`handoff_final_project()` is an explicit action using the existing F010
`write_integration_package()` (which calls `build_ai_video_editor_manifest()`).
There is no incomplete override in F014. The v1 adapter format is unchanged.
Source-tree output is refused. Approval and preparation create no package, extract
no clip, render no video and never invoke AI_Video_Editor.

## GUI

The seven-panel layout and existing fixed widths/heights remain. The review area
adds a compact preparation/options/final-approval row. “Chọn candidate” retains
F009 accepted semantics; Chờ, Loại and A/B retain their meanings. Candidate review
does not mark the scene finally selected or add it to the selected filmstrip.

Workflow completion retains results only. “Chuẩn bị clip cuối” explicitly prepares
reviewable ranges; “Duyệt clip cuối” is disabled until valid options exist. The
range and final score appear in the option chooser. Explicit approval creates or
replaces one final record, updates the filmstrip/scene indication and recalculates
F010 readiness. The export panel displays readiness reasons; its explicit package
button is disabled until READY. Output directory changes recalculate the report.

FinalReviewWorker runs preparation and approval-time hashing off the GUI thread;
queued signals apply results in GUI slots. Project/script/candidate changes
invalidate pending review results. Closing during a final worker defers closure.
Project-name or script replacement clears final selection to prevent cross-project
reuse. SceneSelectionIndex keeps its original CandidateRecord semantics; filmstrip
cards are presentation projections of final records, not project-building inputs.

## Storage, security and limitations

Final selections are session-only: there is no added persistence or raw provider
response storage. F012's existing provenance allowlist, known credential redaction
and signed-URL query removal are reused for final records. Rights, creator, license
references, media identity and verification provider remain attached. No new runtime
dependency, download or database format is introduced.

Files are rechecked when preparing and approving. Existing finalized records are
authoritative human snapshots, not continuously watched filesystem entries; F010
retains its existing readiness semantics. Handoff uses source paths and ranges,
not an extracted clean clip library. There is no new extraction, rendering,
session recovery, multi-user storage or automatic alternative selection. Disk
integrity checks assume application-controlled storage, as in F012/F013.

## Offline acceptance

Verified baseline: 275 passed at `50c97504764aae1601b9c1a501b364c90a312544`.
F014 focused suite: 35 passed. Full regression: 310 passed. Offline GUI smoke passes.

Run focused tests with the external pytest temp directory:

```powershell
$f014Tests = @(Get-ChildItem tests/test_*f014*.py | ForEach-Object { $_.FullName })
.\.venv\Scripts\python.exe -m pytest -q $f014Tests --basetemp="D:\YouTubeTools\Bin_Finder\pytest_tmp"
.\.venv\Scripts\python.exe -m pytest -q --basetemp="D:\YouTubeTools\Bin_Finder\pytest_tmp"
git diff --check
```

The offline GUI smoke is `test_offline_gui_smoke_separates_candidate_and_final_approval`.
It disables discovery, uses fixture evidence/local files outside source, checks
worker thread execution, and proves candidate acceptance != final selection,
followed by explicit approval -> SelectedClipRecord -> recalculated AcceptanceReport.
Approval creates no export directory. Other tests explicitly exercise blocked and
READY F010 package writes exclusively under the external pytest temp directory.
