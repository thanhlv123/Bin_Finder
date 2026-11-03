# Bin Finder roadmap

## Lộ trình v2 (từ 2026-11-03)

### Định nghĩa 1.0

Bin Finder 1.0 đi từ **kịch bản → video cuối hoàn chỉnh**: nhập kịch bản → AI viết visual brief theo từng câu/cụm lời → tìm footage nhiều nguồn (Pexels, Pixabay, Coverr, Wikimedia Commons, Storyblocks nếu có API, YouTube có công tắc bật/tắt) → chấm khớp 2 tầng (embedding lọc nhanh, VLM xác nhận top 3) → người chọn hoặc AI tự chọn → voice TTS → dựng theo mốc thời gian giọng, hiệu ứng, nhạc, phụ đề → tự kiểm tra chất lượng → xuất MP4 + credits.

Chạy được headless bằng một lệnh `bin_finder run`. **1.0 đạt khi làm trọn một video thật và chủ dự án chấm đạt.** Đây là đích phát triển; lịch sử bên dưới ghi năng lực đã merge.

### Các mốc R0–R7

| Mốc | Mô tả | Tiêu chí xong |
| --- | --- | --- |
| R0 — Dọn dẹp | Đồng bộ tài liệu, version 0.2.0 và CI. | Phạm vi thống nhất, giữ lịch sử, toàn bộ pytest pass. |
| R1 — Visual brief theo câu (đang làm, PR chờ) | AI chuyển từng câu/cụm lời thành visual brief và chuỗi shot bám ngữ cảnh. | Duyệt được brief kịch bản thật, truy vết về lời gốc, chỉ rõ phần không có hình phù hợp. |
| R2 — Nguồn footage | Thêm Coverr, Commons, công tắc YouTube, giấy phép; giữ discovery tách acquisition. | Tìm được ứng viên từ nguồn cấu hình; tắt YouTube thì không gọi nguồn; chỉ media được phép mới đủ điều kiện dựng. |
| R3 — Chấm khớp + AI tự chọn + màn hình duyệt | Embedding lọc nhanh, VLM xác nhận top 3; chọn tay hoặc AI tự chọn, thay/khóa lựa chọn. | Đánh giá footage thật có nhãn người duyệt; giữ source rotation, anti-adjacent reuse, anti-overlap và báo ca không chắc. |
| R4 — Sản xuất video | TTS, dựng theo mốc thời gian giọng, hiệu ứng, nhạc, phụ đề. | Video xem được với hình, tiếng, phụ đề đồng bộ theo voice thật. |
| R5 — Tự kiểm tra + xuất | Kiểm tra chất lượng trước khi xuất MP4 + credits. | Phát hiện thiếu media, lỗi timing/âm thanh/phụ đề và quyền chưa rõ; MP4 phát được, credits truy vết nguồn. |
| R6 — Headless `bin_finder run` | Nối toàn bộ pipeline qua một lệnh với cấu hình rõ ràng. | Một lệnh đi từ kịch bản đến MP4 + credits không cần GUI, báo lỗi và trạng thái đủ để kiểm tra. |
| R7 — Nghiệm thu 1.0 | Làm trọn một video thật để chủ dự án đánh giá. | Chủ dự án xem video cuối và chấm đạt 1.0. |

### Ngoài 1.0

- VPS/multi-user.
- News backend.
- AI_Video_Editor consumer.

### Quy tắc thực hiện

Không mở hướng nghiên cứu ngoài lộ trình. Mỗi mốc một nhánh `feature/rN-*`, một PR.

### Backlog

### Nghiên cứu đã đóng

Đóng hướng nghiên cứu độc lập trong lộ trình; không đóng hay merge các PR này. Ý tưởng được xem xét ở mốc tương ứng, chưa mặc nhiên là tính năng hoàn thành hay bằng chứng chất lượng footage.

- [PR #30 — ZB-01](https://github.com/thanhlv123/Bin_Finder/pull/30): ý tưởng giữ lại cho mốc R1 — intent bám câu hiện tại, truy vấn hình có thể quan sát, no_match và kiểm tra đầu ra có cấu trúc; JSON hợp lệ chưa chứng minh khớp hình.
- [PR #31 — ZB-02](https://github.com/thanhlv123/Bin_Finder/pull/31): ý tưởng giữ lại cho mốc R1 — khối kể chuyện và chuỗi shot nhiều–nhiều với câu, search/hold/transition/graphic; transition chưa tự tạo thời lượng hình dựng được.
- [PR #32 — ZB-03A](https://github.com/thanhlv123/Bin_Finder/pull/32): ý tưởng giữ lại cho mốc R3 — màn hình duyệt storyboard, thay và khóa từng shot; timing và thumbnail thử nghiệm chưa phải timeline media thật.
- [PR #33 — BF-S01](https://github.com/thanhlv123/Bin_Finder/pull/33): ý tưởng giữ lại cho mốc R1 — hợp đồng beat/visual slot bám lời gốc, truy vấn subject/moment/action và phát hiện kịch bản đã đổi.
- [PR #34 — BF-S02](https://github.com/thanhlv123/Bin_Finder/pull/34): ý tưởng giữ lại cho mốc R2 — tìm đa nguồn theo slot, cân bằng pool giữa trục truy vấn/nguồn, khử trùng và giữ lựa chọn đã khóa khi tìm lại.
- [PR #35 — BF-S03A](https://github.com/thanhlv123/Bin_Finder/pull/35): ý tưởng giữ lại cho mốc R3 — xếp hạng metadata có lý do, phân biệt bằng chứng hành động với trùng danh từ; heuristic chưa xác nhận nội dung video.
- [PR #36 — BF-S03B](https://github.com/thanhlv123/Bin_Finder/pull/36): ý tưởng giữ lại cho mốc R3 — kiểm tra media local được phép và cầu nối VLM F021; giữ kết quả bất định, yêu cầu xem chuyển động khi frame tĩnh chưa đủ.
- [PR #37 — BF-S04A](https://github.com/thanhlv123/Bin_Finder/pull/37): ý tưởng giữ lại cho mốc R1 — shot plan biên tập 1–5 giây bám nguồn lời, tách tư liệu thật/stock minh họa/symbolic/graphic; ví dụ tay chưa phải AI tự hiểu kịch bản.
- [PR #38 — BF-S04A.1](https://github.com/thanhlv123/Bin_Finder/pull/38): ý tưởng giữ lại cho mốc R1 — sinh shot plan bằng Ollama local, kiểm tra JSON nghiêm ngặt, chuẩn hóa nhãn ngôn ngữ có giới hạn; không tự sửa nội dung hay cấp quyền media.
- [PR #39 — BF-S04A.2](https://github.com/thanhlv123/Bin_Finder/pull/39): ý tưởng giữ lại cho mốc R5 — quality gate đối chiếu yêu cầu biên tập do người viết, báo thiếu coverage/sắc thái; coverage văn bản chỉ là tư vấn, chưa chứng minh hình đúng.
- [PR #40 — BF-S06](https://github.com/thanhlv123/Bin_Finder/pull/40): ý tưởng giữ lại cho mốc R2 — YouTube discovery metadata có bật/tắt, gợi ý giấy phép không thay quyền tải; cắt MP4/JPEG từ master local được cấp phép, không tự tải video YouTube.

## Lịch sử F001–F021

F001–F021: **đã merge, CI pass**. Các số liệu nghiệm thu bên dưới được giữ làm lịch sử.
F021: merge qua PR #29 (2026-11-03); độ chính xác trên footage thật chưa kiểm chứng.

The accepted F001.5 workspace layout remains fixed unless a real usability bug requires a change.

- F001: GUI shell, project/scene models, selected-footage library contract. **Merged, CI pass**
- F002: Real discovery providers for YouTube / Storyblocks / Pexels / Pixabay / Local; News deferred. **Merged, CI pass**
- F003: Candidate intelligence foundation — content hash, FFprobe metadata, timed transcript sidecars, shot boundaries, reusable analysis cache. **Merged, CI pass**
- F004: Hybrid retrieval — transcript/text similarity + exact/BM25 lexical relevance + visual scoring provider contract + score fusion + retrieval evaluation harness. **Merged, CI pass**
- F005: Context verification/VLM reranking contract — subject, action, location, object, time, visual quality, conflict penalties, confidence thresholds, safe fallback. **Merged, CI pass**
- F006: Smart clip planning/extraction — target 5.0s, 3.5–7.0s bounds, shot-aware trim, optional anchor time, safe local FFmpeg extraction. **Merged, CI pass**
- F007: Local footage intelligence — incremental indexing, local-first search, content-hash reuse, transcript-aware refresh, perceptual search-by-image baseline. **Merged, CI pass**
- F008: Source diversity — source cooldown, anti-adjacent reuse, anti-overlap, duplicate suppression, quality guardrails, unresolved flags. **Merged, CI pass**
- F009: Human review — persistent accept/reject/waitlist decisions, A/B comparisons, evaluation summaries, compact review controls. **Merged, CI pass**
- F010: Real 1–3 minute script acceptance, unresolved-scene gating, quality metrics, and stable AI_Video_Editor manifest adapter. **Merged, CI pass**

F011: Live provider integration. **Merged, CI pass**. See [F011 contract](F011_LIVE_PROVIDERS.md).

F012: Authorized media acquisition and local cache. **Merged, CI pass**. See [F012 contract](F012_AUTHORIZED_MEDIA_ACQUISITION.md).

F013: Acquisition-to-analysis orchestration and resume. **Merged, CI pass**. See [F013 contract](F013_ACQUISITION_ANALYSIS_ORCHESTRATION.md).

F014: Workflow review and explicit final clip selection integration. **Merged, CI pass (offline acceptance)**.
Reuses F008 diversity and F010 acceptance/adapter; candidate acceptance remains
separate from final clip approval. See
[F014 contract](F014_WORKFLOW_REVIEW_FINAL_SELECTION.md).

F015: Final footage export library. **Merged, CI pass (offline + real FFmpeg smoke)**.
READY-only explicit export reuses F006 extraction, validates approved source
hashes, publishes a complete scene-ordered library atomically, and writes a
versioned manifest with optional CSV and materialized F010 adapter. Cooperative
QThread cancellation leaves no completed partial library. Original F010 source
coordinates authorize export; adapter coordinates are local to trimmed clips.
A–B–A passes without changing F010 overlap semantics or adapter v1. Acceptance:
53 focused passed, 363 full regression passed, one Windows symlink-privilege skip;
real offline FFmpeg A–B–A smoke passed. See
[F015 contract](F015_FINAL_FOOTAGE_EXPORT.md).

F016: Versioned session persistence and recovery. **Merged, CI pass (Windows CI + real FFmpeg smokes)**. Scene/UI snapshots and allowlisted final-selection serialization with local SHA-256 revalidation are implemented; remote F012 cache proof is implemented; MAX_PATH paths fail closed; offline real-FFmpeg
restore -> SHA-256 revalidation -> F010 READY -> F015 export smoke passes. READY is never
persisted and is always recomputed. Acceptance: Windows CI 407 passed, 0 skipped (pinned
FFmpeg 9.0.2, SHA-256 verified); real F015 and F016 restore/export smokes PASS.
Validated F013 workflow identity/hash references are historical hints only,
not restored approvals.
GUI lifecycle restores validated state and recomputes F010/F015 readiness. See [F016 contract](F016_SESSION_RECOVERY.md).

F017: Stable handoff contract and portable footage package. **Merged, CI pass (Windows CI +
real FFmpeg handoff acceptance)**: run #157 (ID 39816530610) success, 471 passed,
0 skipped, 0 failed, pinned FFmpeg 9.0.2 SHA-256 verified; F015/F016/F017 real smokes
PASS. AI_Video_Editor integration is not part of F017. Opt-in `_bin_finder_handoff.json`
(`bin_finder_handoff_v1`) built inside the F015 staging transaction, package-relative
paths, read-only `verify_handoff_package()`, real FFmpeg move/tamper/missing smoke.
Legacy adapter v1 and F010/F014/F015/F016 semantics unchanged. See
[F017 contract](F017_STABLE_HANDOFF_CONTRACT.md).

F018: Production script scene planning and context enrichment. **Merged, CI pass; local acceptance PASS**. Deterministic `scene_planning` replaces the GUI
prototype split (3.5–7.0 s scenes aligned to one F006 clip each; long narration splits into more scenes); raw scenes carry searchable context and a documented heuristic
verification fallback. F010 60–180 s policy untouched; F019 owns long-form acceptance.
See [F018 contract](F018_PRODUCTION_SCENE_PLANNING.md).

F019: Production long-form acceptance policy. **Merged, CI pass; local acceptance PASS**. F010 default stays 60–180 s; GUI readiness and F015 export use
`production_acceptance_policy()` (min 60 s, no upper ceiling). Other gates, F014, F006,
F017 schemas unchanged. See [F019 contract](F019_LONG_FORM_ACCEPTANCE.md).

F020: Portable handoff GUI. **Merged, CI pass; local acceptance PASS**.
Panel 7 exposes the F017 handoff (checked by default, independent of the legacy adapter);
core `ExportOptions().handoff` stays opt-in. No schema or acceptance changes; consumer
integration still not implemented. See [F020 contract](F020_PORTABLE_HANDOFF_GUI.md).

F021: Real VLM verification. **Implemented; offline acceptance PASS, live Ollama pipeline smoke PASS
(qwen3-vl:4b), real-footage accuracy not validated, Windows CI pending**. Local Ollama vision provider over bounded FFmpeg frames with strict parsing
and per-unit heuristic fallback, wired into the production workflow. F005 contract and F014
human approval unchanged. See [F021 contract](F021_REAL_VLM_VERIFICATION.md).

## Architecture principles learned from public footage-search projects

Bin Finder follows a clean-room design inspired by common retrieval patterns:

1. Discovery first, acquisition authorization separately.
2. Metadata search narrows candidate videos but does not prove visual relevance.
3. Candidate videos are split into real shots before semantic/VLM scoring.
4. Hybrid retrieval combines transcript, lexical, and visual evidence.
5. Retrieval changes are measured with Top-1, Recall@K, and MRR before replacing defaults.
6. A slower verification stage reranks only the strongest candidates and safely falls back on provider failure.
7. Smart clip planning preserves natural shot boundaries whenever the shot fits the duration policy.
8. Local indexing is incremental and uses content identity to avoid unnecessary rework.
9. Local-first discovery can skip external APIs when a strong local match already exists.
10. Final selection enforces source diversity and non-overlapping ranges without forcing low-quality alternatives.
