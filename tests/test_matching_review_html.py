from test_matching_selector import inputs
from bin_finder.matching import MatchConfig, select_footage
from bin_finder.matching.review_html import render_review_html


def test_html_escape_and_video():
    footage_plan, brief_plan = inputs()
    result = select_footage(footage_plan, brief_plan, MatchConfig(vlm_enabled=False))
    row = result.cues[0]['ranked'][0]
    row['title'] = '<script>alert(1)</script>'
    row['source_url'] = 'javascript:alert(1)'
    page = render_review_html(result)
    assert '<video' in page and row['preview_url'] in page
    assert 'AI đã chọn' in page and 'Cần duyệt' in page
    assert '<script>alert' not in page and '&lt;script&gt;' in page
    assert 'javascript:' not in page and 'http://' not in page
    assert 'decisions.json' in page
