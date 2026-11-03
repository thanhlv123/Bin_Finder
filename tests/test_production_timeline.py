"""Selection eligibility and word-aligned timeline round trips."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from bin_finder.footage.service import FootagePlan
from bin_finder.matching.decisions import apply_decisions
from bin_finder.matching.models import SelectionPlan
from bin_finder.production import MissingSelectionError
from bin_finder.production.narration import Narration
from bin_finder.production.timeline import Timeline, build_timeline, resolve_selections

FIXTURES = Path(__file__).parent / "fixtures/production"


def plans():
    selection = SelectionPlan.from_dict(json.loads((FIXTURES / "selection.json").read_text()))
    footage = FootagePlan.from_dict(json.loads((FIXTURES / "footage.json").read_text()))
    return selection, footage


def test_timeline_boundaries():
    selection, footage = plans()
    narration = Narration(b"", [], {"cue-1": 0.1, "cue-2": 2.3, "cue-3": 4.1}, 6, 2)
    narration.cue_block_indices = {"cue-1": 0, "cue-2": 0, "cue-3": 1}
    timeline = build_timeline(selection, footage, narration)
    assert [shot.block_index for shot in timeline.shots] == [0, 0, 1]
    assert [shot.start for shot in timeline.shots] == [0.1, 2.3, 4.1]
    assert [shot.end for shot in timeline.shots] == [2.3, 4.1, 8]
    assert Timeline.from_dict(timeline.to_dict()) == timeline


def test_missing_selection_and_suggestion():
    selection, footage = plans()
    selection.cues[1]["selected_source_id"] = None
    selection.cues[1]["status"] = "needs_review"
    with pytest.raises(MissingSelectionError, match="cue-2: Green trees"):
        resolve_selections(selection, footage)
    assert resolve_selections(selection, footage, True)[1]["origin"] == "suggested"


@pytest.mark.parametrize("change", [dict(provider="youtube"), dict(reference_only=True),
                                    dict(license={"usable_in_video": False}), dict(license={})])
def test_unusable_never_resolves(change):
    selection, footage = plans()
    footage.cues[0]["candidates"][0].update(deepcopy(change))
    with pytest.raises(MissingSelectionError, match="cue-1"):
        resolve_selections(selection, footage, True)


def test_decisions_applied():
    selection, footage = plans()
    selection.cues[0]["selected_source_id"] = None
    decisions = json.loads((FIXTURES / "decisions.json").read_text())
    revised = apply_decisions(selection, decisions)
    assert resolve_selections(revised, footage)[0]["origin"] == "selected"
    assert revised.cues[0]["status"] == "locked"


def test_candidate_must_belong_to_cue():
    selection, footage = plans()
    selection.cues[0]["selected_source_id"] = "pexels:2"
    with pytest.raises(MissingSelectionError):
        resolve_selections(selection, footage)
