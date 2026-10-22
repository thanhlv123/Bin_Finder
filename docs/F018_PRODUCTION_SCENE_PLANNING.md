# F018 — Production Script Scene Planning & Context Enrichment

Status: implemented; local acceptance PASS (Windows CI pending until pushed).

## Why `_prototype_split` was insufficient

The old GUI path replaced newlines with spaces, split on `"."`, made every fragment a
scene, fixed `target_duration=5.0` and left `SceneContext` empty. Abbreviations and
decimals ("Dr.", "3.5") produced fragments, paragraphs and `! ? …` were ignored, and
an empty context made every F005 heuristic dimension `None`: `verification_score`
was `None`, units became `low-confidence`, and F014 could never offer a final option
for a raw-script scene.

## Planner (`bin_finder.scene_planning`)

Qt-free, network-free, dependency-free and deterministic. `ScenePlanner(policy).plan(script)`
returns `ScenePlanningResult(scenes)` of `SceneRecord`s with IDs `scene_001…`, order
`1…`, `english_text`, estimated `target_duration` and enriched `SceneContext`.
The same script and policy always give identical scenes. The script is inert text:
it is never executed or used as a path, nothing is logged or persisted by the planner.

### Segmentation policy
1. Unicode NFC, `\r\n`→`\n`, control characters removed, tabs/NBSP/repeated spaces collapsed.
2. Blank lines are **hard** paragraph boundaries; single newlines are soft boundaries.
3. Sentences end at `. ! ? …` and `。！？` (runs such as `?!`/`...` and closing quotes/brackets
   stay attached). A `.` does not end a sentence after known abbreviations (Mr, Dr, U.S,
   etc., Vietnamese ông/bà/TS…), single-letter initials, or before a digit after "No".
   Decimals never split because a boundary needs trailing whitespace.
4. Sentences with no letters/digits are dropped. Sentences over `max_scene_words` (17) are
   split at clause marks (`, ; : — –`) and then at word boundaries.
5. Within a paragraph, a group shorter than `min_scene_words` (8) absorbs following
   sentences while staying ≤ `max_scene_words`; a short tail merges backwards. A scene of
   fewer than two words is folded into a neighbour when the result stays within
   `max_scene_words`.

### Bounds (fail safe)
`max_input_chars=50000` and `max_scenes=1000` (both match session snapshot limits). Oversized input
raises `ScenePlanningError("script-too-long" | "too-many-scenes" | "script-not-text")`;
the GUI shows the code in the workflow status and keeps the previous scenes. Empty input
yields no scenes and the GUI does nothing, as before.

### Duration estimate
`target_duration = clamp(words / 2.5, 3.5, 7.0)` rounded to 0.1 s (`words_per_second`,
`min_duration`, `max_duration` in `ScenePlanningPolicy`). The defaults equal F006's
`ClipPolicy` (3.5–7.0 s) so **one planned scene maps to one final F006 clip**. Long
narration is therefore split into additional scenes (`max_scene_words=17`, i.e. at most
6.8 s at 2.5 words/s) instead of producing a scene whose duration exceeds the clip
maximum. `ScenePlanningPolicy.validate()` rejects any custom policy where
`max_scene_words / words_per_second > max_duration`. This is a per-scene narration
estimate only. **F010's 60–180 s acceptance policy is unchanged**; project-level
long-form acceptance is F019.

### Context enrichment (conservative, text-derived)
- `location`: capitalized phrase (≤3 words) directly after a locative preposition
  (in/at/near/across/…; Vietnamese ở/tại/trong/…), excluding days and months. It can
  also capture an organization after "at"; it never looks anything up.
- `subject`: person/group nouns from a small closed lexicon, with up to two directly
  preceding age/size modifiers or capitalized words that already appear in the text.
- `objects`: closed lexicon of concrete nouns; adjacent ones form one phrase ("office lights").
- `action`: closed verb lexicon with inflections, plus `-ing` words (minus a noun
  exclusion list), with a directly following adverb such as "late".
- `keywords`: place + subject/object, subject + action, place + object, and **always** a
  normalized content-word phrase of the scene text as the final fallback.
- `mood`, `avoid`, `suggested_sources` stay empty. Nothing is inferred (no age, ethnicity,
  religion, politics); every value's words occur in the scene text (tested).

## Fallback for empty structured context
`build_scene_queries` already falls back to keywords and scene words. F018 makes the
keywords always non-empty and adds one minimal F005 change: when subject, action,
location and objects are all absent, `HeuristicContextVerifier` scores coverage of the
scene's content words in the unit text and reports it through `object_match`, with the
explanation "Keyword fallback from scene text". Scenes with any structured dimension
behave exactly as before; scoring weights, reranking and `VerificationDimensions` are
unchanged. F014 still requires explicit `human_approved=True`; nothing is auto-approved.

## GUI
`MainWindow._split_script` replaces `_prototype_split` on the same signal; the seven
panels and the button are unchanged. Lifecycle is unchanged: unresolved session state
and final selections are invalidated, workflow results and final options cleared, F010
readiness refreshed, the first scene selected and searched, session save scheduled.
Search is triggered twice per split (scene-list selection plus the explicit call), as before.

## Limitations
- Lexicons are English-centric and intentionally small; Vietnamese and other languages get
  segmentation, locations after Vietnamese prepositions, and keyword fallback only.
- Raw script is stored in `english_text` (no translation; `vietnamese_text` stays empty).
- Heuristic text coverage is not visual verification. No LLM/VLM/embedding is used.
- The button label still reads "Chia cảnh tự động (AI)" (GUI text deliberately untouched).
- F019 handles project-level long-form acceptance and duration planning.

Tests: `tests/test_scene_planning_f018.py`, `tests/test_gui_scene_planning_f018.py`.
