from test_matching_selector import inputs
from bin_finder.matching import MatchConfig, select_footage, apply_decisions


def test_decisions_and_rerun():
    footage_plan, brief_plan = inputs()
    config = MatchConfig(vlm_enabled=False)
    decisions = {
        'version': 1,
        'decisions': {
            'C0001': {'source_id': 'pexels:1', 'lock': True},
            'C0002': {'source_id': 'pexels:1'},
            'C0003': {'source_id': None},
            'C0004': {'source_id': 'unknown'},
        },
    }
    result = apply_decisions(select_footage(footage_plan, brief_plan, config), decisions)
    assert result.cues[0]['status'] == 'locked'
    assert result.cues[1]['status'] == 'manual'
    assert 'adjacent_reuse_warning' in result.cues[1]['flags']
    assert result.cues[2]['selected_source_id'] is None
    assert 'decision_unknown_candidate' in result.cues[3]['flags']
    again = apply_decisions(select_footage(footage_plan, brief_plan, config), decisions)
    assert again.cues[0]['selected_source_id'] == result.cues[0]['selected_source_id']
