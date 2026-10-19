from bin_finder.analysis.scene_detection import build_shots, parse_ffmpeg_scene_times


def test_parse_ffmpeg_scene_times_and_build_shots():
    stderr = """
[Parsed_showinfo_1] n:0 pts:3072 pts_time:3.200 pos: 100
[Parsed_showinfo_1] n:1 pts:7200 pts_time:7.500 pos: 200
"""
    cuts = parse_ffmpeg_scene_times(stderr)
    shots = build_shots(cuts, 10.0)

    assert cuts == [3.2, 7.5]
    assert [(shot.start, shot.end) for shot in shots] == [
        (0.0, 3.2),
        (3.2, 7.5),
        (7.5, 10.0),
    ]


def test_build_shots_dedupes_and_discards_invalid_boundaries():
    shots = build_shots([-1, 0, 2.0, 2.0, 20.0], 5.0)
    assert len(shots) == 2
    assert shots[0].index == 1
    assert shots[1].duration == 3.0


def test_build_shots_requires_known_duration():
    assert build_shots([1.0], 0.0) == ()
