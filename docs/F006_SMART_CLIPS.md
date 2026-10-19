# F006 — Smart Clip Planning and Safe Extraction

F006 turns verified shot-level results into renderable clip proposals.

## Default duration policy

- target: 5.0 seconds
- minimum: 3.5 seconds
- maximum: 7.0 seconds

A shot already inside the 3.5–7.0 second range is kept whole so Bin Finder does not introduce an unnecessary cut through the visual action.

A shot longer than 7 seconds receives a 5-second window. The window is centered on an optional anchor time when later analysis can provide one; otherwise it uses the shot midpoint.

A shot shorter than 3.5 seconds is rejected by default instead of crossing a scene boundary. A policy can explicitly allow short shots when required.

## Extraction

The FFmpeg extractor works only with a local/authorized source path. It never enables overwrite by default and runs FFmpeg without a shell.

The default extraction mode re-encodes the short range for accurate timing. Stream-copy mode remains available for cases where speed matters more than frame-accurate boundaries.

## GUI

No panel, splitter, width, height, or workflow order is changed by F006.
