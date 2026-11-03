"""Apply explicit human choices without silently overriding them."""
from copy import deepcopy


def apply_decisions(selection_plan, decisions):
    plan = deepcopy(selection_plan)
    if decisions.get('version') != 1 or not isinstance(decisions.get('decisions'), dict):
        raise ValueError('invalid decisions')
    for cue in plan.cues:
        decision = decisions['decisions'].get(cue['cue_id'])
        if decision is None:
            continue
        source = decision['source_id']
        match = next((row for row in cue['ranked'] if row['source_id'] == source), None)
        if source is not None and match is None:
            cue['flags'].append('decision_unknown_candidate')
            continue
        cue['selected_source_id'] = source
        if source:
            cue['status'] = 'locked' if decision.get('lock') else 'manual'
        else:
            cue['status'] = 'needs_review'
        cue['selection_origin'] = cue['status'] if source else None
        cue['confidence'] = match['final_score'] if match else 0
    for previous, cue in zip(plan.cues, plan.cues[1:]):
        if cue['selected_source_id'] and cue['selected_source_id'] == previous['selected_source_id']:
            if 'adjacent_reuse_warning' not in cue['flags']:
                cue['flags'].append('adjacent_reuse_warning')
    for status in ('auto_selected', 'needs_review', 'manual', 'locked'):
        plan.stats[status] = sum((cue_row['status'] == status for cue_row in plan.cues))
    return plan
