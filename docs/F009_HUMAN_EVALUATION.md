# F009 — Human Review and A/B Evaluation

F009 adds persistent human feedback without changing the accepted seven-panel geometry.

## Review decisions

Every candidate can be recorded as:

- accepted
- rejected
- waitlist

The latest decision for the same scene/candidate pair replaces the older one. Review state is stored outside the repository under the Bin Finder local application data area.

## A/B comparisons

The review panel exposes a compact A/B control. The first click arms candidate A; after selecting another candidate from the same scene, the second click opens a small winner prompt. The winner is stored as an A/B comparison record.

A/B records are evaluation evidence only. They do not silently replace the currently selected footage.

## Evaluation summary

The review store can report counts for accepted/rejected/waitlist decisions, total comparisons, and per-candidate wins. This is the foundation for F010 quality evaluation and tuning.

## GUI contract

F009 does not move panels, change fixed workspace widths/heights, or add a new panel. It only replaces the existing review action row with compact controls inside the same location.
