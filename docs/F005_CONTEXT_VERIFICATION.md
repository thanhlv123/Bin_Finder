# F005 — Context Verification and VLM Reranking

F005 adds a top-N verification stage after F004 hybrid retrieval without changing the accepted GUI layout.

## Verification dimensions

A verification provider can score:

- subject match
- action match
- location match
- object match
- time match
- visual quality
- context conflict

Context conflict is a penalty signal and is especially important for scene "avoid" constraints.

## Provider contract

The verification layer is provider-independent. A future local or cloud VLM can implement the same batch interface.

F005 does not add a new VLM runtime dependency. The default provider is a text-only heuristic fallback using transcript/metadata evidence. This improves context filtering now while preserving a clean upgrade path to a true VLM.

## Top-N behavior

Only the strongest F004 results are sent to verification. The verified block is reranked internally; unverified tail results stay after the verified block. Provider errors or malformed score counts fall back safely to the F004 order instead of failing the search.

## Next milestone

F006 will convert high-ranked verified shots into smart 3.5–7.0 second clip proposals centered on natural shot boundaries.
