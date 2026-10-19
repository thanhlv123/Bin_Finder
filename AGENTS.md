# Bin Finder engineering rules

- Target OS: Windows 10/11.
- Python: 3.12.
- GUI: PyQt6.
- Keep GUI, core models, provider integrations, semantic ranking, acquisition, and export separated.
- No provider secret may be printed, committed, or written to manifests.
- Search/discovery and media acquisition are separate capabilities.
- A candidate may be discoverable but not render-eligible.
- Scene ID is stable across footage replacements; clip ID identifies a concrete selected clip.
- Selected footage must support source rotation, anti-adjacent reuse, and anti-overlap.
- Final project library is a clean folder of approved clips plus machine-readable manifests.
- Do not add new runtime dependencies without approval.
- Do not add VPS/multi-user work until Windows-local quality is accepted by the user.
