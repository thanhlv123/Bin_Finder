"""Deterministic quality checks without external services."""
from copy import deepcopy
from pathlib import Path
import pytest
from bin_finder.production.timeline import Timeline, Shot
from bin_finder.production.config import ProductionConfig
from bin_finder.qa.checks import check_streams, check_timeline, check_media, check_analysis, check_words


@pytest.fixture
def timeline(tmp_path):
    media = tmp_path / 'source.mp4'
    media.touch()
    shot = Shot('cue1', 'xin chào', 0, 6, 'source', 'pexels', str(media), 'selected', {'usable_in_video': True, 'source_url': 'https://example.org/video', 'creator': 'Author', 'license_name': 'CC0'}, clip_out=6)
    return Timeline([shot], 6, [{'word': 'xin', 'start': 0, 'end': 2}, {'word': 'chào', 'start': 2, 'end': 4}], end_hold=2)


def codes(findings):
    return {(item.code, item.severity) for item in findings}


def test_streams():
    metadata = {'video': {'width': 1920, 'height': 1080, 'fps': 30, 'codec': 'h264', 'pix_fmt': 'yuv420p'}, 'audio': {'codec': 'aac'}}
    assert not check_streams(metadata, ProductionConfig())
    assert ('missing_video_stream', 'blocker') in codes(check_streams({}, ProductionConfig()))
    metadata['video'].update(width=1280, fps=25, codec='hevc')
    assert codes(check_streams(metadata, ProductionConfig())) == {('resolution_mismatch', 'blocker'), ('fps_mismatch', 'blocker'), ('video_format', 'warning')}


def test_timing(timeline):
    assert not check_timeline({'duration': 6}, timeline)
    assert ('duration_mismatch', 'blocker') in codes(check_timeline({'duration': 7}, timeline))
    timeline.shots.append(deepcopy(timeline.shots[0]))
    timeline.shots[1].start = 6.1
    assert ('timeline_gap', 'blocker') in codes(check_timeline({'duration': 6}, timeline))


@pytest.mark.parametrize('change,code,severity', [({'license': {'usable_in_video': False}}, 'unusable_license', 'blocker'), ({'provider': 'youtube'}, 'unusable_license', 'blocker'), ({'origin': 'suggested'}, 'suggested_clip', 'warning'), ({'end': 1}, 'short_shot', 'warning'), ({'clip_out': 0}, 'invalid_clip_range', 'blocker'), ({'speed': 3}, 'clip_speed', 'warning'), ({'local_path': ''}, 'missing_media', 'blocker')])
def test_media_errors(timeline, change, code, severity):
    assert not check_media(timeline, 'https://example.org/video Author')
    for name, value in change.items():
        setattr(timeline.shots[0], name, value)
    assert (code, severity) in codes(check_media(timeline, 'https://example.org/video Author'))


def test_credits_sources(timeline):
    timeline.shots[0].license['attribution_required'] = True
    assert ('missing_attribution', 'blocker') in codes(check_media(timeline, 'https://example.org/video'))
    assert ('missing_credits', 'blocker') in codes(check_media(timeline, None))
    assert ('missing_source_credit', 'blocker') in codes(check_media(timeline, 'Author'))
    timeline.shots[0].local_path = 'absent.mp4'
    assert ('missing_source_file', 'warning') in codes(check_media(timeline, 'Author'))
    assert ('missing_source_file', 'blocker') in codes(check_media(timeline, 'Author', True))


def test_reuse(timeline):
    timeline.shots.append(deepcopy(timeline.shots[0]))
    result = codes(check_media(timeline, 'https://example.org/video'))
    assert ('repeated_source', 'warning') in result
    assert ('adjacent_overlap', 'warning') in result


def test_analysis(timeline):
    assert not check_analysis({'lufs': -14, 'true_peak': -2}, timeline)
    assert ('black_frames', 'blocker') in codes(check_analysis({'black': [[2, 3]]}, timeline))
    assert ('black_frames', 'warning') in codes(check_analysis({'black': [[0, .5]]}, timeline))
    assert not check_analysis({'silence': [[4, 6]]}, timeline)
    assert ('silence', 'warning') in codes(check_analysis({'silence': [[1, 3]]}, timeline))
    assert ('silence', 'blocker') in codes(check_analysis({'silence': [[0, 3.5]]}, timeline))
    assert ('loudness', 'warning') in codes(check_analysis({'lufs': -17}, timeline))
    assert ('loudness', 'blocker') in codes(check_analysis({'lufs': -20}, timeline))
    assert ('true_peak', 'warning') in codes(check_analysis({'true_peak': 0}, timeline))
    assert ('freeze_frames', 'warning') in codes(check_analysis({'freeze': [[1, 4]]}, timeline))
    timeline.shots[0].notes.append('Ken Burns')
    assert ('freeze_frames', 'info') in codes(check_analysis({'freeze': [[1, 4]]}, timeline))


def test_words(timeline):
    assert not check_words(timeline)
    timeline.words[1]['start'] = -1
    assert ('word_order', 'blocker') in codes(check_words(timeline))
    timeline.words[1]['word'] = 'khác'
    assert ('word_coverage', 'blocker') in codes(check_words(timeline))
    timeline.words = []
    assert ('missing_words', 'blocker') in codes(check_words(timeline))


def test_old_manifest_and_subtitle_groups(timeline):
    payload = timeline.to_dict()
    for name in ('subtitles', 'music_path', 'end_hold'):
        payload.pop(name)
    assert Timeline.from_dict(payload).subtitles is True
    timeline.words = [{'word': 'xin chào', 'start': 0, 'end': .1}]
    assert ('subtitle_timing', 'warning') in codes(check_words(timeline))
    timeline.subtitles = False
    assert not check_words(timeline)


def test_remaining_timing_edges(timeline):
    timeline.shots[0].start = .1
    assert not check_timeline({'duration': 6}, timeline)
    timeline.shots[0].end = 5
    assert ('last_shot_end', 'warning') in codes(check_timeline({'duration': 6}, timeline))
    timeline.shots[0].end = 0
    assert ('invalid_shot_duration', 'blocker') in codes(check_timeline({'duration': 6}, timeline))


def test_missing_license_and_long_shot(timeline):
    timeline.shots[0].license = None
    timeline.shots[0].end = 13
    result = codes(check_media(timeline, ''))
    assert ('unusable_license', 'blocker') in result
    assert ('unclear_license', 'warning') in result
    assert ('long_shot', 'info') in result


def test_subtitle_overlap_and_word_end(timeline):
    timeline.words = [{'word': 'xin', 'start': index * .1, 'end': 2} for index in range(8)]
    result = codes(check_words(timeline))
    assert ('subtitle_timing', 'warning') in result
    timeline.words[0]['end'] = 7
    assert ('words_past_duration', 'blocker') in codes(check_words(timeline))
    timeline.words[0]['end'] = -1
    assert ('word_order', 'blocker') in codes(check_words(timeline))


def test_coverage_warning(timeline):
    expected = [f'word{index}' for index in range(40)]
    timeline.shots[0].text = ' '.join(expected)
    timeline.words = [{'word': word, 'start': index / 10, 'end': (index + 1) / 10} for index, word in enumerate(expected[:-1])]
    assert ('word_coverage', 'warning') in codes(check_words(timeline))


def test_intentional_final_frame(timeline):
    timeline.shots[0].notes = ['Source exhausted after 0.8x slowdown; final frame extended with gentle zoom']
    assert ('freeze_frames', 'info') in codes(check_analysis({'freeze': [[3, 6]]}, timeline))


@pytest.mark.parametrize('kind,intervals', [('black', [[1, 2], [3, 4]]), ('freeze', [[0, 2], [3, 6]])])
def test_visual_ranges_grouped_with_source(timeline, kind, intervals):
    timeline.shots[0].source_id = '219749'
    timeline.shots[0].provider = 'pixabay'
    finding, = check_analysis({kind: intervals}, timeline)
    assert finding.details['ranges'] == intervals
    assert finding.details['total_duration'] == sum(end - start for start, end in intervals)
    assert finding.details['source_id'] == '219749'
    assert finding.details['provider'] == 'pixabay'
    assert 'pixabay:219749 (cue cue1)' in finding.message


def test_black_crossing_shot_boundary(timeline):
    second = deepcopy(timeline.shots[0])
    timeline.shots[0].end = 3
    second.start = 3
    second.cue_id = 'cue2'
    second.source_id = 'other'
    timeline.shots.append(second)
    findings = check_analysis({'black': [[2, 4], [4.5, 5.5]]}, timeline)
    assert [finding.cue_id for finding in findings] == ['cue1', 'cue2']
    assert findings[0].details['ranges'] == [[2, 3]]
    assert findings[1].details['ranges'] == [[3, 4], [4.5, 5.5]]
    assert findings[1].details['total_duration'] == 2
