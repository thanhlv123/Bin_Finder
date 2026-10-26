# BF-S03B — Local Vision Access Gate (Research, Phase 0)

**Stacked on:** `research/bf-s03a-metadata-ranking`, Draft PR #35.  
**Implementation branch:** `research/bf-s03b-local-vision-gate`.  
**Status:** local-media handoff guard only. NO Ollama calls, FFmpeg frame reads, provider searches, clip downloads, automatic timeline selection or licensing approval.

## Evidence: user-local BF-S03A.1 trial

- 26/26 dedicated tests passed on Windows, six source requests returned successfully, 26 unique clips discovered, 20 metadata-ranked candidates.
- Before action-verb correction: `pixabay:1104` rank 1 / score 87, `pexels:10020348` rank 10 / 47, `pixabay:330501` oil refinery rank 9 / 49.
- After correction: `pexels:10020348` rank 1 / 55 with `related-motion-only`; `pixabay:1104` rank 2 / 47 with `not-described`; `pixabay:330501` rank 10 / 9.
- **19 of 20 ranked items contain NO described requested action predicate; remaining one has related movement, not confirmed harbor entry**. No metadata supports visual confirmation of *at dawn*.
- Report says `FRAME_OR_LICENSING_VERIFIED: False`; users should not interpret metadata score as probability of match. This is why BF-S03B needs real frame evidence, abstention and human approval.

## Existing F021 Vision research must be reused, not duplicated

The separate **unmerged** `feature/f021-real-vlm-verification` research branch contains:
- `src/bin_finder/verification/frame_sampler.py`: FFmpeg in-memory bounded JPEG sampling at 20%, 50%, 80% of one local segment, max 6 frames, max 960 pixels wide, max 2 MB per frame, no temp images or outbound network.
- `src/bin_finder/verification/ollama_vlm.py`: local-only Ollama `http://127.0.0.1:11434` using `qwen3-vl:4b`, disabled redirect/proxy, bounded response bytes, strict dimensions with null for unobservable facts, no cloud uploads. Recorded trials show model output budget matters and empty responses must remain **not verified**.
- F021 verification is based on `SceneRecord` + `RetrievalUnit`. BF-S03B must adapt **BF-S01 VisualSlot + BF-S02 CandidateHit + BF-S03A RankedSlotCandidate** into those verification inputs, without silently conflating scene selection, dates/locations, or ratings.
- These F021 files are **not present in BF-S03A base**. Phase 0 does not copy/cherry-pick incomplete F021 development into production; an isolated integration review and compatibility tests are required first.

## Phase 0 gate implemented now

`src/bin_finder/search/slot_local_vision_gate.py` adds a read-only `prepare_local_vision` contract:

1. Requires explicit `approve_local_inspection=True` to begin local file validation. Default is **no approval**, zero provider/model calls.
2. No automatic mapping from a provider URL into local media. Human supplies each candidate key, absolute local file path and explicit start/end seconds.
3. Every key must belong to the given BF-S03A rank result; at most five manually nominated candidates per attempt. An empty list does not auto-select top five.
4. Files must already exist under a specifically allowed directory; reject missing/nonvideo/outside-root/symlink/junction/remote paths, invalid ranges, empty/oversized files.
5. Result's `prepared` items have `local-sample-ready-not-verified` status. This is *only eligible for a future bounded sampler* and is **not** evidence that video contents match the script.
6. `PreparedVisionUnit.source_file` deliberately excludes the path from dataclass repr for safer logging. No frame bytes, full paths, API URLs, temporary signed URLs, keys, or private local metadata are exported in any report here.
7. Output `model_calls=0`, `provider_calls=0`, even with explicit local-inspection approval.

**Tests**: `tests/test_bf_s03b_local_vision_gate.py`, all synthetic/temp files. No user footage or Ollama requests. Windows CI includes full old test suite, real FFmpeg export regression and GUI smoke, without running local Ollama.

## Next phase (not implemented yet)

- **BF-S03B Phase 1**: Write a reviewed compatibility bridge to the F021 frame sampler/verifier, using only already-owned/authorized local videos. Add a second **separate opt-in to allow local Ollama inference**. Refuse remote/untrusted endpoints; no network except explicit loopback. No automatic download.
- **Evidence**: timestamp/frame count, visible subject/action, movement direction, time-of-day cues, explicit `must_show`/`must_not_show` and unobservable/ambiguous/missing data as **unknown**. A few sampled still frames cannot prove approach-to-harbor motion; request more temporal evidence or human video playback.
- **Human labels**: use small real clips with user labels `direct_match`, `context_only`, `conflict`, `unknown`, scoring top-5 precision against the existing BF-S03A.1 baseline; keep labels out of prompts to avoid test leakage.
- **Final approval** always separate: neither VLM scores nor reported rights_status permits timeline selection or content reuse automatically.

## Local Windows pilot gate

First validate the gate only with offline pytest (on a fresh `--basetemp` directory under drive D). Do not upload media or API keys. Do not ask to download Pexels/Pixabay video to try the gate: existing local clips can be provided via explicit file paths in a later phase only when authorized.


## BF-S03B Phase 1 — Reused F021 sampler/Ollama verifier and second approval

**Implementation** (still on this isolated research branch, NOT merged into production):

- Reused exact source bodies from `feature/f021-real-vlm-verification`: `verification/frame_sampler.py` (F021 original blob `8b3d4369ce2738421494f2cea5a6d5fa8b1dacda`) and `verification/ollama_vlm.py` (blob `9112dd4c0b93f78f2e49391c66bc9ccb63ea9c42`). Shared `models.SceneRecord`, `retrieval.models.RetrievalUnit` and `verification.models.VerificationResult` were already present on this branch. No external proprietary code copied.
- New `search/slot_local_vision_bridge.py`: `verify_local_vision(plan, preapproved_local_gate, approve_local_inference=False, config=None)` transforms the selected BF-S01 `VisualSlot` into the existing F021 scene context, and a bounded local `PreparedVisionUnit` into `RetrievalUnit`. The editorial **visual brief** becomes the visual request, rather than treating the narrator's possibly figurative literal words as visible facts. `must_show` maps to visible objects; `must_not_show` to avoid criteria. Action query and required entities remain separate observable fields.
- **Second separate explicit permission:** `approve_local_inspection=True` only authorizes preparation of a local file through Phase 0. Inference additionally requires `approve_local_inference=True`. With this false the bridge **does not instantiate Ollama or sample any frame**. With it true, the F021 verifier samples *3 in-memory frames* from each user-approved local clip and sends JPEG evidence only to validated loopback Ollama (no proxy or redirect), 0 cloud calls, 0 provider calls, 0 media downloads.
- Default bridge config for the 3-frame thinking model is `VlmConfig(model='qwen3-vl:4b', url='http://127.0.0.1:11434', num_ctx=8192, num_predict=4096, frames=3)`, matching a previous F021 local success where 2048 output tokens had produced incomplete JSON. For the available separate instruct model, an explicit validated `VlmConfig(model='qwen3-vl:4b-instruct')` can be supplied after model availability is checked. No model can bypass the loopback host validation.
- No automatically approved match: the result is one of `local-inference-approval-required`, `no-approved-local-media`, `local-vision-mode-off`, `vision-unavailable-or-abstained`, `vision-inconclusive-human-review`, or `vision-provisional-human-review`; every assessment has `human_review_required=True`, and the run has `timeline_approved=False` always.
- Nullable `subject_match`, `action_match`, `time_match` are preserved as **unknown**, not 0 or "verified". High predicted `context_conflict` is only `possible-must-not-show-conflict`, for manual inspection. The code explicitly attaches `temporal-action-requires-human-playback` for direct-evidence visual slots, since 20/50/80% still frames alone may not establish "entering the harbor". Model explanation is never printed in bridge result. The existing F021 verifier returns None on model/transport/JSON error; no heuristic is substituted silently.
- `tests/test_bf_s03b_local_vision_bridge.py` is fully offline and injects fake local responses to cover second approval, mapping of scene to slot visual cues, timing, missing/invalid response, conflict, non-loopback URL rejection, no path/exception leaks, and F021 sampler/model config compatibility. Windows CI runs against the entire existing suite.

**Operational restriction:** No CLI with automatic user media discovery or unapproved local file sampling has been added. A *later* explicit single-clip manual trial will require the user to choose a specific local video path under a restricted root and separately authorize Ollama inference. Neither the copied F021 implementation nor tests here demonstrate that the real footage shows the desired action, time or place. BF-S03B Phase 1 is implementation + offline compatibility tests, not yet local real-media/VLM acceptance.
