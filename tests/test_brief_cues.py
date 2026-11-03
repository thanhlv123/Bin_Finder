from pathlib import Path
import re
import pytest
from bin_finder.brief import split_cues, Cue
from bin_finder.scene_planning import _words

FIXTURE = Path(__file__).parent / "fixtures/brief/k1_excerpt.md"


def test_fixture_preserves_narration_and_chapters():
    script = FIXTURE.read_text(encoding="utf-8")
    cues = split_cues(script)
    assert cues == split_cues(script)
    assert {c.chapter for c in cues} == {"INTRO", "CH1"}
    assert [c.cue_id for c in cues] == [f"C{i:04d}" for i in range(1,len(cues)+1)]
    expected = " ".join(line.strip() for line in script.splitlines() if not line.startswith("#"))
    assert " ".join(c.text for c in cues) == " ".join(expected.split())
    assert all(3 <= c.word_count <= 18 for c in cues)
    assert all(Cue.from_dict(c.to_dict()) == c for c in cues)


@pytest.mark.parametrize("limit", [3, 6, 12, 18])
def test_long_sentences_short_fragments_and_markdown(limit):
    script = "## CH1\n**Look here.** A doctor carefully reads the report, and checks the sample before calling the patient. Yes."
    cues = split_cues(script, limit)
    assert " ".join(c.text for c in cues) == "Look here. A doctor carefully reads the report, and checks the sample before calling the patient. Yes."
    assert all(c.word_count >= 3 for c in cues)
    assert all(c.word_count <= limit or c.word_count < 6 for c in cues)


def test_empty_and_short_chapter():
    assert split_cues("## INTRO\n\n") == []
    assert split_cues("## INTRO\nHello.")[0].text == "Hello."
    with pytest.raises(ValueError):
        split_cues("text", 2)
