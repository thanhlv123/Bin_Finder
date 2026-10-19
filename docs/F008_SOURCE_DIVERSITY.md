# F008 — Source Diversity and Anti-Overlap

F008 adds a deterministic final-selection stage after ranking, verification, and smart clip planning. The accepted GUI layout remains unchanged.

## Default policy

- source cooldown: 1 selected clip;
- same source cannot be adjacent;
- same-source time ranges cannot overlap;
- exact/near-identical ranges from the same source are suppressed within a scene;
- an optional duplicate group can suppress visually identical content across providers;
- an alternative is accepted only when its score is within 0.18 of the best scene candidate.

This allows A -> B -> A while rejecting A -> A.

## Quality guardrail

Source diversity must not force a poor clip. If the only conflict-free alternative drops more than the allowed score gap, the scene is marked unresolved with low-context-match instead of selecting low-quality footage.

If every candidate violates cooldown, overlap, duplicate, or range rules, the scene is marked diversity-conflict.

## Determinism

Candidates are ordered by score and stable tie-breakers. Selection output therefore remains reproducible for the same candidate set and policy.

## Boundaries

F008 does not alter provider discovery, download media, add dependencies, or redesign the GUI.
