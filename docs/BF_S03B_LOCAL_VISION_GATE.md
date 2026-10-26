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
