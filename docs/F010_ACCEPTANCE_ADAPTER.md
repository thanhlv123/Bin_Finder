# F010 — Real-Script Acceptance and AI_Video_Editor Adapter

F010 defines the final local acceptance gate before Bin Finder is integrated into AI_Video_Editor.

## Acceptance policy

The default acceptance target is a 1–3 minute script:

- expected scene duration total: 60–180 seconds;
- every scene must have selected footage;
- selected footage must meet the minimum final score;
- no adjacent source-reuse violations;
- no overlapping ranges from the same source.

The report lists every unresolved or low-score scene instead of claiming completion.

## Stable adapter

Bin Finder exports a versioned JSON contract:

`ai_video_editor_bin_finder_adapter_v1`

Each script scene includes its stable `scene_id`, order, text, target duration, and one selected footage record with local path, source range, score fields, rights status, and stable `clip_id`.

## Safety boundary

F010 does not modify AI_Video_Editor. It only produces a deterministic integration package so the existing editor can consume it later after real Windows acceptance is approved.

By default an integration package is not written when acceptance fails. An explicit `allow_incomplete=True` is available only for research/testing.
