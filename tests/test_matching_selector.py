import json
import pytest
from pathlib import Path
from dataclasses import replace
from bin_finder.brief import BriefPlan
from bin_finder.footage.service import FootagePlan
from bin_finder.matching import MatchConfig, SelectionPlan, select_footage
from bin_finder.matching.vlm_score import VisualVerdict


def inputs():
    root = Path(__file__).parent / 'fixtures/matching'
    return (
        FootagePlan.from_dict(json.loads((root / 'footage.json').read_text())),
        BriefPlan.from_dict(json.loads((root / 'briefs.json').read_text())),
    )


def test_offline_selection():
    footage_plan, brief_plan = inputs()
    result = select_footage(footage_plan, brief_plan, MatchConfig(vlm_enabled=False))
    assert result.cues[0]['status'] == 'auto_selected'
    assert result.cues[0]['selected_source_id'] != result.cues[1]['selected_source_id']
    assert result.cues[3]['flags'] == ['vlm_missing', 'no_candidates']
    assert 'only_reference' in result.cues[4]['flags']
    assert all(('vlm_missing' in cue['flags'] for cue in result.cues))
    assert result.stats['text_seconds'] >= 0 and result.stats['vlm_seconds_per_cue'] >= 0
    assert SelectionPlan.from_dict(result.to_dict()) == result


def test_threshold_and_no_match():
    footage_plan, brief_plan = inputs()
    low = select_footage(footage_plan, brief_plan, MatchConfig(vlm_enabled=False, auto_select_threshold=1))
    assert 'low_confidence' in low.cues[0]['flags']

    class Judge:
        def judge(self, *args):
            return VisualVerdict('no_match', 0, 'Wrong action', False)
    result = select_footage(
        footage_plan, brief_plan, MatchConfig(vlm_top_n=10), Judge(), lambda *args: b'image',
    )
    assert result.cues[0]['selected_source_id'] is None
    assert 'vlm_no_match' in result.cues[0]['flags']


def test_provider_rotation():
    footage_plan, brief_plan = inputs()
    footage_plan = replace(footage_plan, cues=footage_plan.cues[:3])
    result = select_footage(
        footage_plan,
        brief_plan,
        MatchConfig(vlm_enabled=False, no_adjacent_reuse=False, source_cooldown=2),
    )
    assert [cue['selected_source_id'] for cue in result.cues] == ['pexels:1', 'pexels:1', 'pixabay:2']


def test_config_loading(tmp_path, monkeypatch):
    path = tmp_path / 'config'
    path.mkdir()
    (path / 'matching.local.json').write_text(json.dumps({'top_k': 4, 'vlm_enabled': True}))
    monkeypatch.setenv('BIN_FINDER_MATCH_VLM_ENABLED', 'false')
    monkeypatch.setenv('BIN_FINDER_MATCH_MIN_VLM_SCORE', '0.8')
    monkeypatch.setenv('BIN_FINDER_MATCH_THUMBNAIL_HOSTS', 'images.pexels.com,cdn.coverr.co')
    config = MatchConfig.load(tmp_path)
    assert config.top_k == 4 and (not config.vlm_enabled)
    assert config.min_vlm_score == 0.8
    assert config.thumbnail_hosts == ['images.pexels.com', 'cdn.coverr.co']


def test_visual_match_and_uncertainty():
    footage_plan, brief_plan = inputs()

    class Judge:
        def __init__(self, match):
            self.match = match

        def judge(self, *args):
            return VisualVerdict(self.match, 0.95, 'Thumbnail evidence', self.match == 'uncertain')
    config = MatchConfig(vlm_top_n=10)
    result = select_footage(footage_plan, brief_plan, config, Judge('match'), lambda *args: b'image')
    row = next(
        (row for row in result.cues[0]['ranked'] if row['source_id'] == result.cues[0]['selected_source_id']),
    )
    assert row['final_score'] == round(0.4 * row['text_score'] + 0.6 * 0.95, 6)
    assert result.cues[0]['status'] == 'auto_selected'
    uncertain = select_footage(footage_plan, brief_plan, config, Judge('uncertain'), lambda *args: b'image')
    assert uncertain.cues[0]['status'] == 'needs_review'
    assert 'needs_motion_check' in uncertain.cues[0]['flags']


class RecordingJudge:
    def __init__(self, match="partial", score=0.6):
        self.match = match
        self.score = score
        self.sources = []

    def judge(self, brief, cue_text, candidate, image):
        self.sources.append(candidate["source_id"])
        return VisualVerdict(self.match, self.score, "Thumbnail evidence", False)


def controlled_candidates(monkeypatch, thumbnail_urls):
    from bin_finder.matching.text_score import ScoredCandidate

    footage_plan, brief_plan = inputs()
    footage_plan = replace(footage_plan, cues=footage_plan.cues[:1])
    candidates = [
        dict(
            footage_plan.cues[0]["candidates"][0],
            source_id=f"pexels:{index}",
            thumbnail_url=thumbnail_url,
            reference_only=False,
        )
        for index, thumbnail_url in enumerate(thumbnail_urls)
    ]
    # All rows clear the text threshold; a visual partial scores below unjudged text.
    monkeypatch.setattr(
        "bin_finder.matching.selector.score_candidates",
        lambda *args: [ScoredCandidate(candidate, 0.9, []) for candidate in candidates],
    )
    return footage_plan, brief_plan


def test_unjudged_candidate_cannot_bypass_visual_partial(monkeypatch):
    footage_plan, brief_plan = controlled_candidates(monkeypatch, ["first", "second"])
    judge = RecordingJudge(score=0.7)
    result = select_footage(
        footage_plan, brief_plan, MatchConfig(vlm_top_n=1), judge, lambda *args: b"image",
    )
    cue = result.cues[0]
    assert cue["ranked"][0]["source_id"] == "pexels:1"
    assert cue["selected_source_id"] == "pexels:0"
    assert judge.sources == ["pexels:0"]
    assert "vlm_missing" not in cue["flags"]


def test_unjudged_candidate_cannot_bypass_visual_rejection(monkeypatch):
    footage_plan, brief_plan = controlled_candidates(monkeypatch, ["first", "second"])
    result = select_footage(
        footage_plan, brief_plan, MatchConfig(vlm_top_n=1),
        RecordingJudge("no_match", 0), lambda *args: b"image",
    )
    assert result.cues[0]["status"] == "needs_review"
    assert result.cues[0]["selected_source_id"] is None
    assert "vlm_no_match" in result.cues[0]["flags"]


def test_missing_thumbnails_require_review_but_no_vlm_keeps_text_selection(monkeypatch):
    footage_plan, brief_plan = controlled_candidates(monkeypatch, [None, "broken"])
    judge = RecordingJudge()
    result = select_footage(
        footage_plan, brief_plan, MatchConfig(), judge, lambda *args: None,
    )
    assert result.cues[0]["status"] == "needs_review"
    assert result.cues[0]["selected_source_id"] is None
    assert "vlm_missing" in result.cues[0]["flags"]
    assert judge.sources == []
    text_only = select_footage(footage_plan, brief_plan, MatchConfig(vlm_enabled=False))
    assert text_only.cues[0]["status"] == "auto_selected"


def test_thumbnail_absence_does_not_consume_visual_budget(monkeypatch):
    footage_plan, brief_plan = controlled_candidates(monkeypatch, [None, "second", "third"])
    judge = RecordingJudge(score=0.7)
    fetched = []

    def fetch(url, config):
        fetched.append(url)
        return b"image"

    result = select_footage(footage_plan, brief_plan, MatchConfig(vlm_top_n=2), judge, fetch)
    assert fetched == ["second", "third"]
    assert judge.sources == ["pexels:1", "pexels:2"]
    assert result.stats["vlm_calls"] == 2
    assert result.cues[0]["selected_source_id"] == "pexels:1"


@pytest.mark.parametrize("score", [-0.01, 1.01, float("nan"), float("inf")])
def test_min_vlm_score_rejects_invalid_values(score):
    with pytest.raises(ValueError, match="min_vlm_score"):
        MatchConfig(min_vlm_score=score)


@pytest.mark.parametrize("score", [0, 1])
def test_min_vlm_score_accepts_boundaries(score):
    assert MatchConfig(min_vlm_score=score).min_vlm_score == score


@pytest.mark.parametrize("match", ["match", "partial"])
@pytest.mark.parametrize("score,threshold,selected", [
    (0.6, 0.6, False),
    (0.7, 0.6, True),
    (0.7, 0.9, False),
])
def test_visual_score_gate(monkeypatch, match, score, threshold, selected):
    footage_plan, brief_plan = controlled_candidates(monkeypatch, ["first"])
    config = MatchConfig(auto_select_threshold=threshold)
    assert config.min_vlm_score == 0.7
    result = select_footage(
        footage_plan, brief_plan, config,
        RecordingJudge(match, score), lambda *args: b"image",
    )
    cue = result.cues[0]
    assert (cue["status"] == "auto_selected") == selected
    assert ("low_visual_confidence" in cue["flags"]) == (score < 0.7)


def test_top_three_verdicts_do_not_flag_unjudged_candidates(monkeypatch):
    footage_plan, brief_plan = controlled_candidates(monkeypatch, [str(i) for i in range(10)])
    result = select_footage(
        footage_plan, brief_plan, MatchConfig(),
        RecordingJudge(score=0.8), lambda *args: b"image",
    )
    cue = result.cues[0]
    assert sum(row["vlm"] is not None for row in cue["ranked"]) == 3
    assert "vlm_missing" not in cue["flags"]


def test_no_visual_budget_flags_missing_verdicts(monkeypatch):
    footage_plan, brief_plan = controlled_candidates(monkeypatch, ["first"])
    result = select_footage(
        footage_plan, brief_plan, MatchConfig(vlm_top_n=0), RecordingJudge(),
    )
    assert result.cues[0]["status"] == "needs_review"
    assert "vlm_missing" in result.cues[0]["flags"]


def test_youtube_preference_config(tmp_path, monkeypatch) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/matching.local.json").write_text(json.dumps({"youtube_preference": 0.2}))
    assert MatchConfig.load(tmp_path).youtube_preference == 0.2
    monkeypatch.setenv("BIN_FINDER_MATCH_YOUTUBE_PREFERENCE", "0.3")
    assert MatchConfig.load(tmp_path).youtube_preference == 0.3
    for value in (-0.1, 1.1, float("nan")):
        with pytest.raises(ValueError):
            MatchConfig(youtube_preference=value)
