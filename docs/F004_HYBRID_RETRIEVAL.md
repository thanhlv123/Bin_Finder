# F004 — Hybrid Retrieval

F004 ranks shot/time ranges inside media already analyzed by F003.

The GUI layout is unchanged.

## Retrieval signals

1. BM25 lexical relevance over shot transcript plus supplied metadata.
2. Exact phrase/context matches from scene subject, action, location, objects, and keywords.
3. Pluggable text-similarity provider.
4. Pluggable visual-similarity provider.
5. Weighted score fusion with missing signals automatically removed from the denominator.

The default text provider is a dependency-free token-cosine baseline. It keeps the pipeline functional without adding a new runtime package. The provider contract can later be replaced by a true embedding model.

The default visual provider returns no score because no visual embedding runtime is approved yet. Tests use fake visual providers to verify that real visual scores can participate in ranking without changing the engine contract.

## Shot alignment

F003 shot boundaries define retrieval units. Transcript segments are attached to every shot they overlap. Each unit stores source path, start/end time, transcript text, metadata text, and transcript coverage.

## Boundaries

F004 does not download remote media, call a VLM, or change the accepted seven-panel GUI. VLM verification is F005.
