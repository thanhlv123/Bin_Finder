import json
import pytest
from bin_finder.brief import BriefConfig, split_cues
from bin_finder.brief.providers import OllamaBriefProvider, HeuristicBriefProvider


@pytest.mark.parametrize('mode', ['success', 'invalid', 'connection', 'disabled'])
def test_single_retry(mode):
    config = BriefConfig(provider='ollama', retry_single=mode != 'disabled')
    cues = split_cues('A doctor reads a report. A nurse walks outside.')
    rows = [b.to_dict() for b in HeuristicBriefProvider(config).propose(cues, {'cues': cues})]
    calls = []
    def client(url, payload, **kwargs):
        requested = json.loads(payload['messages'][1]['content'])['requested']
        calls.append(requested)
        if mode == 'connection':
            raise ConnectionError('offline')
        data = rows[:1] if len(calls) == 1 else [rows[1]] if mode == 'success' else []
        return {'message': {'content': json.dumps({'briefs': data})}}
    result = OllamaBriefProvider(config, client).propose(cues, {'cues': cues})
    assert len(calls) == (1 if mode in ('connection', 'disabled') else 2)
    assert result[1].origin.startswith('llm:') if mode == 'success' else result[1].origin == 'heuristic'
    if mode in ('success', 'invalid'):
        assert [r['cue_id'] for r in calls[1]] == [cues[1].cue_id]
