# F021 — Real VLM Verification

Status: implemented; offline acceptance PASS; **live Ollama pipeline smoke PASS**. Real-footage
accuracy is **not** validated. Windows CI pending until pushed.

## Acceptance evidence
**Pipeline acceptance (PASS, 2026-10-23, Windows, Ollama 0.40.8, model `qwen3-vl:4b`,
endpoint `http://127.0.0.1:11434`):** `python -m bin_finder.verification.ollama_smoke --approve-live-vlm`
printed `PASS_F021_REAL_VLM: ollama-vlm:qwen3-vl:4b confidence=1.00`. FFmpeg sampled 3 JPEG
frames from a synthetic clip, the frames went to the local model only, the real response parsed
into a `VerificationResult` with provider `ollama-vlm:qwen3-vl:4b`, all seven dimensions non-null
and confidence 1.0. This proves the end-to-end path (sampling, transport, strict parsing,
provider identity), nothing more.

**Real-footage accuracy validation (NOT DONE):** the smoke input is a trivial solid red 4 s clip,
so the 1.0 scores say nothing about how well the model judges real stock footage, ambiguous
scenes or negative matches. Precision, recall, latency per candidate and thinking-model behavior
on real footage still need a separate labeled evaluation; do not treat the smoke as a quality claim.

## Layers
- **F005** — the provider contract (`VerificationProvider.verify(scene, units) -> list[VerificationResult | None]`),
  scoring and `VerificationReranker`. Unchanged.
- **F018** — text/context fallback so raw-script scenes are usable by the heuristic verifier. Unchanged.
- **F021** — actual image-frame verification with a local vision model. The heuristic
  verifier judges transcript/metadata text; the VLM provider judges sampled frames.

```text
RetrievalUnit -> bounded FFmpeg frame sampling -> local Ollama /api/chat (images)
  -> strict JSON parse -> VerificationResult -> existing VerificationReranker -> F006/F014
```

## Modules (`bin_finder.verification`)
- `frame_sampler.py` — `FfmpegFrameSampler`: default 3 frames at 20/50/80 % of
  `unit.start..unit.end` (1–6 allowed), in memory via stdout, JPEG only, scaled to at most
  960 px wide, `-fs` and a re-check cap each frame at 2 MB, 30 s per-frame timeout, argument
  list (no shell), `BIN_FINDER_FFMPEG`/PATH discovery. Invalid or non-finite ranges, missing or
  linked sources, missing FFmpeg, timeouts and bad output raise `FrameSamplingError`.
- `ollama_vlm.py` — `OllamaVisionVerifier` (stdlib `urllib`; no new dependency).
  `POST <base>/api/chat`, `stream=false`, `format=json`, temperature 0, seed 0,
  `num_ctx` 8192, `num_predict` 2048 (see "Thinking model and token budget"), base64 frames
  only (never the video, a path or transcript/metadata). Loopback only
  (`127.0.0.1`, `localhost`, `::1`; plain `http`, no credentials/path/query); no system proxy;
  redirects refused; response capped at 1 MiB; no Authorization header, no API key.
  Provider id: `ollama-vlm:<model>`.
- `factory.py` — `FallbackVerificationProvider` and `production_verifier()`.
- `ollama_smoke.py` — explicit live check (below).

## Strict response parsing
A JSON object (a single optional json code fence is tolerated). Each of the seven dimensions
(`subject/action/location/object/time_match`, `visual_quality`, `context_conflict`) must be a
finite number or `null`; `confidence` is required; at least one dimension must be non-null.
Extra keys are ignored; the explanation is control-character-stripped and capped at 300
characters. Out-of-range numbers are **rejected** (F005 would clamp, but a 0–100 answer must not
silently become 1.0), as are NaN/Infinity, booleans, strings and malformed JSON.

## Fallback (mandatory)
Per unit, any frame, transport or parse failure yields `None` from the VLM provider, and the
composite fills exactly that unit with `HeuristicContextVerifier`, preserving order and count.
Each result keeps the `provider` of whoever produced it (`ollama-vlm:…` or `heuristic-context`).
A transport-level failure (Ollama stopped, missing model/404, timeout) stops further requests
for the rest of that `verify()` call so the GUI worker does not wait through every unit.
`VerificationReranker`'s outer fallback is untouched.

## Configuration (all optional; no secrets)
| Variable | Default |
|---|---|
| `BIN_FINDER_VLM_MODE` | `auto` (`auto` / `heuristic` / `off`) |
| `BIN_FINDER_VLM_MODEL` | `qwen3-vl:4b` |
| `BIN_FINDER_OLLAMA_URL` | `http://127.0.0.1:11434` (loopback only) |
| `BIN_FINDER_VLM_TIMEOUT_SECONDS` | `120` (1–600) |
| `BIN_FINDER_VLM_FRAMES_PER_UNIT` | `3` (1–6) |
| `BIN_FINDER_VLM_NUM_CTX` | `8192` (2048–32768) |
| `BIN_FINDER_VLM_NUM_PREDICT` | `2048` (128–8192, and below `NUM_CTX`) |

`auto`: Ollama per unit with heuristic fallback. `heuristic`: never contacts Ollama.
`off`: `production_verifier()` returns `None` (the historical behavior; F014 prepares with its
own heuristic). An invalid mode, model or endpoint never sends frames anywhere and degrades to `heuristic`.

## Production wiring
`MainWindow._process_current_candidate` now builds
`WorkflowService(project_id=…, verifier=production_verifier())`. Construction does no
network or FFmpeg work; verification runs inside the existing `WorkflowWorker` thread, never on
the Qt main thread. F014's `prepare()` fallback path for unconfigured/legacy callers is unchanged.

## Thinking model and token budget
The default `qwen3-vl:4b` is a **Thinking** build: it writes reasoning before the JSON answer.
Three sampled frames cost about 3.3k prompt tokens, so on real footage a 4096-token window or a
600-token output cap is exhausted while it is still thinking, the reply `content` is empty, the
strict parser rejects it and the unit silently falls back to the heuristic verifier.

Real-footage measurements (one clip, `qwen3-vl:4b`, Ollama 0.40.8, 3 frames; not an accuracy study):

| `num_ctx` | `num_predict` | prompt + generated tokens | `done_reason` | result |
|---|---|---|---|---|
| 4096 (Ollama default) | 600 | 3324 + 600 | `length` | empty content, heuristic fallback |
| 4096 (Ollama default) | 2048 | 3324 + 772 = 4096 | `length` | empty content, heuristic fallback |
| 8192 | 2048 | 3324 + 1018 | `stop` | valid JSON, no fallback |

Hence the defaults `num_ctx=8192` and `num_predict=2048`. A larger context window uses more
RAM/VRAM and slows the first load; lower the frame count or choose a non-thinking vision model
if that is a problem. Both values are validated and bounded (above); an invalid value degrades
to the heuristic verifier without contacting Ollama. Thinking text is never stored or logged.
Per-unit latency on the measured clip was about 10–19 s.

## Human approval
A VLM score never approves anything. The path stays VLM verifies/reranks → F006 clip proposal →
**human explicit approval (F014)** → `SelectedClipRecord`.

## Privacy and bounds
Loopback HTTP only; only up to 6 downscaled JPEG frames per unit leave the process (to the local
Ollama); no full video, no remote upload, no persistent frame cache or files, no secrets.
Ollama is optional: Bin Finder launches and works without it. Nothing downloads Ollama or pulls a
model; install it and run `ollama pull qwen3-vl:4b` yourself if you want real visual verification.

## Live smoke (explicit opt-in, never in pytest/CI)
```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m bin_finder.verification.ollama_smoke --approve-live-vlm
```
Without the flag it prints `SKIPPED_NOT_APPROVED`. With it, a tiny synthetic clip is generated in
temporary storage, one frame set is sent to the configured loopback model, and a valid structured
result prints `PASS_F021_REAL_VLM`; an absent Ollama or model exits nonzero with a bounded message.

## Limitations
- Verification quality depends on the local model; the live smoke covered only a synthetic clip; accuracy on real footage is unmeasured.
- The default model is a Thinking build and needs the larger token budget above; a long
  reasoning chain can still exceed `num_predict`, in which case the unit falls back to the
  heuristic. Only one real clip has been measured at the new defaults.
- The heuristic fallback has no transcript for raw footage and scores such units at 0.0, so a
  unit that falls back ranks below verified ones even if it matches.
- Up to `top_n` (8) units × 3 frames per candidate, processed sequentially; slow on CPU-only machines.
- Frames sampled at fixed fractions can miss brief events.

Tests: `tests/test_vlm_verification_f021.py` (fakes, a loopback stub HTTP server with real FFmpeg
frames, and a real-sampler test that skips only when FFmpeg is absent).
