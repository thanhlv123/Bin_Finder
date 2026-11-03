"""Report serialization and HTML escaping."""
from bin_finder.production.timeline import Timeline, Shot
from bin_finder.qa.models import QaReport, Finding
from bin_finder.qa.report import write_html_report, write_json_report
import json


def test_reports(tmp_path):
    report = QaReport('C:/private/movie.mp4', 'production.json', 'now', [Finding('test', 'blocker', '<script>alert(1)</script>')])
    timeline = Timeline([Shot('cue', '<script>', 0, 2, 'source', 'local', '', 'selected', {})], 2, [])
    output = tmp_path / 'report.html'
    write_html_report(report, timeline, output)
    text = output.read_text(encoding='utf-8')
    assert 'Báo cáo kiểm tra video' in text
    assert '<script>' not in text
    assert '&lt;script&gt;' in text
    assert 'C:/private' not in text
    write_json_report(report, tmp_path / 'report.json')
    restored = QaReport.from_dict(json.loads((tmp_path / 'report.json').read_text(encoding='utf-8')))
    assert restored.to_dict() == report.to_dict()
    assert not restored.passed


def test_html_severity_and_time_order(tmp_path):
    report = QaReport('video.mp4', 'production.json', 'now', [
        Finding('warn_late', 'warning', '', start=5),
        Finding('block_late', 'blocker', '', start=4),
        Finding('warn_early', 'warning', '', start=1),
        Finding('block_early', 'blocker', '', start=2),
    ])
    output = tmp_path / 'report.html'
    write_html_report(report, Timeline([], 6, []), output)
    text = output.read_text(encoding='utf-8')
    assert text.index('block_early') < text.index('block_late') < text.index('warn_early') < text.index('warn_late')
