# F019 — Production Long-form Acceptance Policy

Status: implemented; local acceptance PASS (Windows CI pending until pushed).

## Problem

`evaluate_project(project)` uses the historical F010 default policy: expected scene
duration total must be 60–180 s. The GUI readiness check and `FinalExportService`
both used that default, so a complete 5/10/20-minute project was `not_ready` only
because it exceeded 180 s. With F018 producing scenes of at most 7 s, long-form
projects naturally contain dozens or hundreds of scenes.

## Two explicit policies

| | Legacy F010 default | F019 production |
|---|---|---|
| How | `evaluate_project(project)` | `evaluate_project(project, production_acceptance_policy())` |
| Minimum expected duration | 60 s | 60 s |
| Maximum expected duration | 180 s (`expected-duration-above-maximum`) | none |
| Everything else | identical | identical |

`AcceptancePolicy.max_duration_seconds` is now `float | None`; `None` means no
project-level upper limit. A numeric maximum below the minimum is still rejected,
and the dataclass default is still 180.0. No arbitrary 10-minute/30-minute/2-hour cap
is introduced. Report fields, `to_dict()` and every JSON schema are unchanged.

Unchanged gates (both policies): every scene covered, `final_score >= 0.60`, clean
source rotation, no same-source overlap, at least one scene. F006 `ClipPolicy`
(3.5–7.0 s), F018 scene durations, F014 explicit `human_approved=True`, source/hash
verification, and F015/F016/F017 behavior and schemas are untouched.

## `evaluate_project` call sites

| Call site | Policy | Reason |
|---|---|---|
| `gui/main_window.py` `_refresh_acceptance` | **production** | GUI READY gates the export button |
| `final_export.py` `FinalExportService.export` | **production** | must agree with the GUI so a READY project is not re-blocked |
| `final_selection.py` `handoff_final_project` | legacy | explicit F010 compatibility handoff; no proven production reason |
| `handoff_smoke.py`, `session_export_smoke.py` | legacy | 60 s fixtures satisfy both policies; smokes unchanged |
| tests (F010/F012/F013/F014/F017…) | legacy | assert the historical contract |

## Limits that still apply
Long-form is not unlimited. Script input is bounded by F018 (`max_input_chars=50000`,
`max_scenes=1000`), session snapshots accept at most 1000 scenes, and export time and
disk use grow with the number of clips (one extraction per scene). F019 does not
benchmark or optimize those.

## Tests
`tests/test_long_form_acceptance_f019.py`: legacy 60/180/>180; production 185 s
(37 × 5 s), 300 s (60 × 5 s) and 600 s (120 × 5 s) ready; <60 s still blocked; each
other gate still blocks long-form; GUI readiness/export button and `FinalExportService`
agree (fake extractor, no real FFmpeg); `handoff_final_project` remains legacy; F014
approval and F017 schema unchanged. The two existing tests that stub
`core.evaluate_project` (F015, F017) only gained an optional `policy` argument.
