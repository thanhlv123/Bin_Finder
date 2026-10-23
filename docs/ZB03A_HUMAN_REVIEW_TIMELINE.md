# ZB-03A — Human Review Timeline (isolated research prototype)

## Objective

AI can draft a visual story and list footage search intents, but it cannot
guarantee a truthful, fully rendered YouTube documentary. ZB-03A changes the
handoff to a **human reviewable storyboard timeline**: keep useful candidates,
highlight vague/unresolved beats, and allow one candidate to be replaced
without clearing other reviewed shots.

This is **not** a video editor or production footage pipeline yet.

## Relationship to existing components

- Research branch `research/zb03a-human-review-timeline` is **stacked on**
  `research/zb02-narrative-visual-planning` (PR #31), not directly on `main`.
  Its PR should target the ZB-02 branch to keep the proposed changes separate.
- It reuses immutable ZB-02 `VisualStoryPlan` and the `Visual Plan Audit`,
  alongside production `SceneRecord` IDs and **estimated voiceover durations**.
- It does **not** modify existing `SceneRecord`, F018 scene segmentation,
  F014 `FinalSelectionService`, F016 session codec, the production GUI, F021,
  any providers, acquisition or final export.
- Existing production selection assumes one final approved clip per scene;
  ZB-03A does not alter that invariant, and does not attempt a direct F014
  adapter. Scene-to-shot timing compatibility remains unimplemented.

## Implemented now

`src/bin_finder/draft_timeline.py` provides a pure immutable review overlay:
- One draft item per planned shot with stable `shot_id`, `scene_ids`, purpose,
  strategy, and an approximate narration interval obtained from estimated
  `SceneRecord.target_duration`.
- One shot may cover multiple narrated scenes and a scene may have several
  overlapping shot proposals. These are **review coordinates only**, NOT media
  start/end times or an FFmpeg-ready timeline.
- `search` items may contain up to 20 explicitly identified, **unverified**
  candidate references. Selecting a different candidate resets that item's
  layout-review state without touching other shot IDs.
- `mark_reviewed()` is an **explicit human editorial-layout confirmation**;
  it is not clip/media/rights verification or F014 final approval.
- A reviewed search item can be locked and later explicitly unlocked. Locked
  items cannot have candidates, selections or notes changed.
- `hold`, `transition` and `graphic` are deliberately marked
  `needs_editorial_resolution`. They cannot be mistaken for acquired clips
  or final approvals.
- A user may **explicitly select a local file** with extension
  `.mp4/.mov/.mkv/.webm` as an unverified candidate. No automatic file reading,
  decoding, thumbnail generation, asset verification, upload or licensing
  check happens in this module. File content may be invalid despite the
  extension and **must be verified in later workflow**.
- Notes and reviewer choices are only held in memory in this prototype;
  no disk/session persistence or autosave.

`src/bin_finder/timeline_review_gui.py` is a standalone PyQt6 research
window, with narration list, approximate VO timeline, visual-shot cards with
strategy/status labels, candidate selection, manual local replacement,
review and lock buttons, and an independent review-details panel.

All "thumbnail" cards are **text-only mock placeholders**, NOT decoded video
frames or remotely fetched preview images. There is **no live playback** in
ZB-03A (deferred to ZB-03B). The screen explicitly says this.

`src/bin_finder/timeline_review_demo.py` creates synthetic three-genre
trials (travel/history/economy) from the ZB-02 offline examples. Synthetic
candidate titles are **not actual footage search results**.

## Run on Windows

Use the existing Windows Python 3.12 venv, and a separate, clean Git worktree
for the ZB-03A research branch (do not overwrite main or the ZB-02 worktree).

```powershell
$env:PYTHONPATH = 'D:\YouTubeTools\Bin_Finder_ZB03A_Research\src'
$python = 'D:\YouTubeTools\Bin_Finder\Bin_Finder\.venv\Scripts\python.exe'

# Offline no-Qt / no-network preview:
& $python -m bin_finder.timeline_review_demo --genre travel --headless

# Standalone UI (NO production GUI modifications):
& $python -m bin_finder.timeline_review_demo --genre travel
```

Choose `history` or `economy` in the last flag for other synthetic scenes.

In this window: select a shot from VIDEO TRACK; choose an alternative
candidate; press "Thay bằng ứng viên đã chọn"; click "Đã kiểm tra bố cục";
optionally lock/unlock the reviewed shot; add a private note. A local video
can be added only with the explicit file picker. No rendering or final
production approval occurs.

## Tests / stage gates

- `tests/test_zb03a_draft_timeline.py`: immutable state, replacement,
  review, lock, missing alternatives, editor annotations, local-reference
  safety, estimate/time non-finality and no implicit approval.
- `tests/test_zb03a_review_gui.py`: PyQt6 offscreen UI controls and review
  state changes; synthetic files only.
- Windows GitHub Actions must pass all old/new tests.
- Qualitative user review: is shot-to-narration mapping understandable? Is
  it easy to identify vague footage and replace a single candidate? Is it
  obvious that images/timing/rights are **not final**?
- Only then consider **ZB-03B** for real preview thumbnails, local video
  playback, voiceover synchronization, timing/hold resolution and verified
  asset identities, then **ZB-03C** for persistent review sessions, guarded
  handoff and draft export.

**Hard limits:** no claim of usable stock footage, no automatic footage
downloads, no speaking-audio sync, no render-ready time ranges, no final
clip approval, no rights claims, no hidden model calls, no background work,
and no production GUI change.
