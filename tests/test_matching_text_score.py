from test_matching_selector import inputs
from bin_finder.matching.text_score import score_candidates


def test_action_avoid_and_reasons():
    footage_plan, brief_plan = inputs()
    scored = score_candidates(
        brief_plan.briefs[0],
        footage_plan.cues[0]['text'],
        footage_plan.cues[0]['candidates'],
    )
    rows = {scored_candidate.candidate['source_id']: scored_candidate for scored_candidate in scored}
    assert rows['pexels:1'].text_score > rows['commons:3'].text_score
    assert rows['pexels:1'].text_score > rows['coverr:4'].text_score
    assert all((scored_candidate.reasons and all(scored_candidate.reasons) for scored_candidate in scored))
    assert rows['youtube:5'].candidate['reference_only']


def test_object_without_verb_is_not_action_evidence():
    footage_plan, brief_plan = inputs()
    candidate = dict(footage_plan.cues[0]['candidates'][0], title='doctor report hospital')
    scored = score_candidates(brief_plan.briefs[0], '', [candidate])[0]
    assert scored.text_score <= 0.39
    assert 'Action evidence in metadata: 0.00' in scored.reasons
