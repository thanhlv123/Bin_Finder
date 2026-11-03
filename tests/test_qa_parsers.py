"""Offline detector parser tests."""
import pytest
from bin_finder.qa.probe import parse_probe, parse_analysis
from bin_finder.qa.export import parse_loudnorm


def test_probe():
    metadata = parse_probe({'streams': [{'codec_type': 'video', 'codec_name': 'h264', 'width': 1920, 'height': 1080, 'avg_frame_rate': '30000/1001', 'pix_fmt': 'yuv420p'}, {'codec_type': 'audio', 'codec_name': 'aac', 'sample_rate': '48000', 'channels': 2}], 'format': {'duration': '6'}})
    assert metadata['video']['fps'] == pytest.approx(29.97, abs=.01)
    assert metadata['audio']['channels'] == 2
    assert metadata['duration'] == 6
    assert parse_probe({'streams': [{'codec_type': 'video', 'avg_frame_rate': '0/0'}]})['video']['fps'] is None


def test_detectors():
    text = 'black_start:2 black_end:3.5\nlavfi.freezedetect.freeze_start: 1\nfreeze_end: 4\nsilence_start: 2\nsilence_end: 4\nSummary:\n I: -15.2 LUFS\n LRA: 3.1 LU\n Peak: -1.2 dBFS'
    result = parse_analysis(text)
    assert result['black'] == [[2, 3.5]]
    assert result['freeze'] == [[1, 4]]
    assert result['silence'] == [[2, 4]]
    assert result['lufs'] == -15.2
    assert result['lra'] == 3.1
    assert result['true_peak'] == -1.2


def test_incomplete():
    assert parse_analysis('unknown')['parse_notes']
    assert parse_analysis('freeze_start: 2')['parse_notes']
    assert parse_analysis('silence_start: 4', 6)['silence'] == [[4, 6]]
    assert parse_analysis('silence_end: 3')['parse_notes']


def test_loudnorm():
    result = parse_loudnorm('logs {"input_i":"-20", "input_tp":"-3", "input_lra":"2", "input_thresh":"-30", "target_offset":"0.2"} done')
    assert result['input_i'] == -20
    with pytest.raises(ValueError):
        parse_loudnorm('incomplete {')


def test_audio_only_measurement(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from bin_finder.qa import probe
    from bin_finder.production.config import ProductionConfig

    commands = []

    def run(arguments):
        commands.append(arguments)
        return SimpleNamespace(stderr='Summary: I: -14.2 LUFS LRA: 2.0 LU Peak: -1.3 dBFS')

    monkeypatch.setattr(probe, 'run_process', run)
    result = probe.analyze_audio(tmp_path / 'final.mp4', ProductionConfig())
    assert result['lufs'] == -14.2
    assert result['true_peak'] == -1.3
    assert commands[0][commands[0].index('-map') + 1] == '0:a:0'
    assert '-vf' not in commands[0]


def test_normalization_headroom_and_measurements(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from bin_finder.qa import export

    commands = []
    monkeypatch.setattr(export, 'probe_video', lambda *args: {'duration': 6})
    monkeypatch.setattr(export, 'analyze_audio', lambda *args: {'lufs': -14.2, 'true_peak': -1.2})

    def run(arguments):
        commands.append(arguments)
        return SimpleNamespace(stderr='{"input_i": "-20", "input_tp": "-3", "input_lra": "2", "input_thresh": "-30", "target_offset": "0.2"}')

    monkeypatch.setattr(export, 'run_process', run)
    result = export.normalize_loudness(tmp_path / 'input.mp4', tmp_path / 'output.mp4')
    assert 'TP=-1.5' in commands[1][commands[1].index('-af') + 1]
    assert result == {'target_lufs': -14, 'true_peak': -1, 'measured_lufs': -14.2, 'measured_true_peak': -1.2}
