"""CLI behavior with injected local measurement boundaries."""
import json
import pytest
from bin_finder.qa import __main__ as cli


def test_missing(tmp_path):
    assert cli.main([str(tmp_path / 'absent.mp4')]) == 2


@pytest.mark.parametrize('strict,expected', [(True, 3), (False, 0)])
def test_reports(tmp_path, monkeypatch, strict, expected):
    video = tmp_path / 'video.mp4'
    video.touch()
    (tmp_path / 'production.json').write_text(json.dumps({'shots': [], 'words': [], 'duration': 6}), encoding='utf-8')
    monkeypatch.setattr(cli, 'probe_video', lambda *args: {'duration': 6})
    monkeypatch.setattr(cli.ProductionConfig, 'load', lambda *args: cli.ProductionConfig())
    arguments = [str(video)] + (['--strict'] if strict else [])
    assert cli.main(arguments) == expected
    assert (tmp_path / 'qa-report.json').is_file()
    assert (tmp_path / 'qa-report.html').is_file()


def test_corrupt_manifest(tmp_path):
    video = tmp_path / 'video.mp4'
    video.touch()
    (tmp_path / 'production.json').write_text('{', encoding='utf-8')
    assert cli.main([str(video)]) == 2

@pytest.mark.parametrize('strict', [False, True])
def test_export_gate_and_final_reports(tmp_path, monkeypatch, strict):
    video = tmp_path / 'video.mp4'
    video.touch()
    (tmp_path / 'production.json').write_text(json.dumps({'shots': [], 'words': [], 'duration': 6}), encoding='utf-8')
    monkeypatch.setattr(cli, 'probe_video', lambda *args: {'duration': 6})
    monkeypatch.setattr(cli.ProductionConfig, 'load', lambda *args: cli.ProductionConfig())
    exports = []

    def export(input, output, *args, **kwargs):
        exports.append(output)
        output.touch()
        return {"measured_lufs": -14.1, "measured_true_peak": -1.3}

    monkeypatch.setattr(cli, 'normalize_loudness', export)
    command = [str(video), '--export', str(tmp_path / 'final.mp4')]
    assert cli.main(command + (['--strict'] if strict else [])) == (3 if strict else 0)
    assert bool(exports) is not strict
    assert (tmp_path / 'qa-report.final.json').exists() is not strict
    assert (tmp_path / 'qa-report.final.html').exists() is not strict


def test_unreadable_video(tmp_path, monkeypatch):
    video = tmp_path / 'video.mp4'
    video.touch()
    (tmp_path / 'production.json').write_text(json.dumps({'shots': [], 'words': [], 'duration': 6}), encoding='utf-8')
    monkeypatch.setattr(cli.ProductionConfig, 'load', lambda *args: cli.ProductionConfig())

    def fail(*args):
        raise OSError('private external diagnostic')

    monkeypatch.setattr(cli, 'probe_video', fail)
    assert cli.main([str(video), '--strict']) == 3
    findings = json.loads((tmp_path / 'qa-report.json').read_text(encoding='utf-8'))['findings']
    assert any(item['code'] == 'unreadable_video' for item in findings)


@pytest.mark.parametrize('duration', [float('nan'), -1, 'six'])
def test_invalid_duration(tmp_path, duration):
    video = tmp_path / 'video.mp4'
    video.touch()
    (tmp_path / 'production.json').write_text(json.dumps({'shots': [], 'words': [], 'duration': duration}), encoding='utf-8')
    assert cli.main([str(video)]) == 2


def test_summary_prioritizes_and_groups(tmp_path, capsys):
    from bin_finder.qa.models import Finding, QaReport
    from bin_finder.production.timeline import Timeline

    findings = [Finding('suggested_clip', 'warning', 'suggestion', f'C{index:04}', index) for index in range(1, 11)]
    findings += [Finding(f'blocking_{index}', 'blocker', 'blocked', start=index) for index in range(7, 0, -1)]
    findings += [Finding('suggested_clip', 'info', 'separate severity')]
    cli.save_report(QaReport('video.mp4', 'production.json', 'now', findings), Timeline([], 10, []), tmp_path)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith('[')]
    assert len(lines) == 9
    assert all(f'blocking_{index + 1}' in lines[index] for index in range(7))
    assert 'suggested_clip ×10: C0001, C0002, C0003, …' in lines[7]
    assert lines[8].startswith('[info]')
