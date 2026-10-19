from bin_finder.analysis.probe import metadata_from_ffprobe


def test_metadata_from_ffprobe_prefers_video_stream_and_detects_audio():
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
                "duration": "12.5",
            },
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "13.0"},
    }
    metadata = metadata_from_ffprobe(payload)

    assert metadata.duration == 12.5
    assert metadata.resolution == "1920x1080"
    assert 29.9 < metadata.fps < 30.0
    assert metadata.codec == "h264"
    assert metadata.has_audio is True


def test_metadata_from_ffprobe_falls_back_to_format_duration():
    payload = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "0/0",
                "r_frame_rate": "25/1",
            }
        ],
        "format": {"duration": "7.25"},
    }
    metadata = metadata_from_ffprobe(payload)
    assert metadata.duration == 7.25
    assert metadata.fps == 25.0
    assert metadata.has_audio is False
