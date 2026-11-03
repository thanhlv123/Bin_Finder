"""Small real FFmpeg smoke test, entirely offline."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest
from bin_finder.qa.__main__ import main
from bin_finder.qa.export import normalize_loudness
from bin_finder.qa.probe import analyze_video, probe_video
from bin_finder.production.config import ProductionConfig


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg unavailable')
def test_real_qa_and_normalization(tmp_path, monkeypatch):
    video = tmp_path / 'video.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', "color=c=white:s=1920x1080:r=30:d=6,drawbox=color=black:t=fill:enable='between(t,2,3.5)'", '-f', 'lavfi', '-i', "sine=frequency=440:duration=6:sample_rate=48000,volume=enable='between(t,2,4)':volume=0", '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(video)], check=True, capture_output=True, timeout=15)
    payload = {'duration': 6, 'words': [{'word': 'xin', 'start': 0, 'end': 6}], 'shots': [{'cue_id': 'cue', 'text': 'xin', 'start': 0, 'end': 6, 'source_id': 'local', 'provider': 'local', 'local_path': str(video), 'origin': 'selected', 'license': {'usable_in_video': True, 'license_name': 'owned', 'source_url': 'https://example.org/local'}, 'clip_in': 0, 'clip_out': 6}]}
    (tmp_path / 'production.json').write_text(json.dumps(payload), encoding='utf-8')
    (tmp_path / 'credits.txt').write_text('https://example.org/local', encoding='utf-8')
    monkeypatch.setattr(ProductionConfig, 'load', lambda *args: ProductionConfig())
    assert main([str(video), '--strict']) == 3
    findings = json.loads((tmp_path / 'qa-report.json').read_text(encoding='utf-8'))['findings']
    assert any(item['code'] == 'black_frames' and item['severity'] == 'blocker' for item in findings)
    assert any(item['code'] == 'silence' for item in findings)
    output = tmp_path / 'final.mp4'
    result = normalize_loudness(video, output)
    assert abs(probe_video(output, ProductionConfig())['duration'] - 6) <= .1
    measured = analyze_video(output, ProductionConfig(), 6)
    assert abs(measured['lufs'] + 14) <= 1.5
    assert measured['true_peak'] <= -1.0
    assert result['measured_lufs'] == measured['lufs']
    assert result['measured_true_peak'] == measured['true_peak']
    assert result['target_lufs'] == -14
    assert result['true_peak'] == -1
