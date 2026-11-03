import json
from pathlib import Path
from bin_finder.matching.__main__ import main


def test_cli(tmp_path):
    fixtures = Path(__file__).parent / 'fixtures/matching'
    output, page = (tmp_path / 'selection.json', tmp_path / 'review.html')
    decisions = tmp_path / 'decisions.json'
    decisions.write_text(
        json.dumps({'version': 1, 'decisions': {'C0001': {'source_id': 'pexels:1', 'lock': True}}}),
    )
    assert main(
        [
            str(fixtures / 'footage.json'),
            '--briefs',
            str(fixtures / 'briefs.json'),
            '-o',
            str(output),
            '--html',
            str(page),
            '--no-vlm',
            '--project-root',
            str(tmp_path),
            '--decisions',
            str(decisions),
        ],
    ) == 0
    assert json.loads(output.read_text(encoding='utf-8'))['cues'][0]['status'] == 'locked'
    assert '<video' in page.read_text(encoding='utf-8')
