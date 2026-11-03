"""Offline speech, alignment and cache contracts."""
from dataclasses import replace
from io import BytesIO
from urllib.error import URLError
import wave

import pytest

from bin_finder.production import ProductionError
from bin_finder.production.config import ProductionConfig
from bin_finder.production.narration import build_narration, cue_blocks
from bin_finder.production.tts import VoiceStudioEngine, WordStamp, align_words, cached_speech


def fake_wav(seconds=2, channels=1, rate=8000):
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(bytes(round(seconds * rate) * channels * 2))
    return output.getvalue()


class FakeEngine:
    def __init__(self):
        self.calls = 0

    def synthesize(self, text):
        self.calls += 1
        return fake_wav()

    def transcribe(self, wav_bytes):
        return []


def test_full_alignment():
    stamps = [WordStamp("Hello", 0.2, 0.7), WordStamp("world", 1, 1.5)]
    assert align_words("Hello, world!", stamps, 2) == [
        WordStamp("Hello,", 0.2, 0.7), WordStamp("world!", 1, 1.5)]


def test_missing_and_extra_asr_words():
    stamps = [WordStamp("extra", 0, 0.1), WordStamp("one", 0.2, 0.5), WordStamp("four", 2, 3)]
    words = align_words("one two three four", stamps, 3)
    assert [word.word for word in words] == "one two three four".split()
    assert words[1].start == 0.5
    assert words[2].end == 2
    assert words[1].end == words[2].start


def test_empty_asr_character_weights():
    assert align_words("a bbb", [], 4) == [WordStamp("a", 0, 1), WordStamp("bbb", 1, 4)]


@pytest.mark.parametrize("url", ["https://example.com", "http://192.168.1.1", "http://localhost/a",
                                     "http://user:password@localhost", "http://localhost?key=no"])
def test_loopback_only(url):
    with pytest.raises(ValueError):
        VoiceStudioEngine(ProductionConfig(tts_url=url))


def test_connection_failure_stops_once(tmp_path):
    engine = VoiceStudioEngine(ProductionConfig(cache_dir=str(tmp_path), tts_block_max_chars=1))
    calls = []

    class OfflineOpener:
        def open(self, *arguments, **keywords):
            calls.append(1)
            raise URLError("offline")

    engine.opener = OfflineOpener()
    with pytest.raises(ProductionError, match="VoiceStudio is not running at"):
        build_narration([dict(cue_id="one", text="First."), dict(cue_id="two", text="Next.")],
                        engine, engine.config)
    assert len(calls) == 1


def test_cache_and_identity(tmp_path):
    engine = FakeEngine()
    config = ProductionConfig(cache_dir=str(tmp_path))
    first = cached_speech("Hello world", engine, config)
    assert cached_speech("Hello world", engine, config) == first
    assert engine.calls == 1
    cached_speech("Hello world", engine, replace(config, seed=8))
    assert engine.calls == 2


def test_block_boundaries_and_gap(tmp_path):
    cues = [dict(cue_id="one", text="Hello."), dict(cue_id="two", text="Next.")]
    assert len(cue_blocks(cues, 100)) == 1
    narration = build_narration(cues, FakeEngine(), ProductionConfig(cache_dir=str(tmp_path), tts_block_max_chars=2))
    assert narration.cue_starts == {"one": 0, "two": 2.4}
    assert narration.duration == 4.4
    assert narration.cue_block_indices == {"one": 0, "two": 1}


def test_config_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BIN_FINDER_PROD_SPEED", "0.8")
    monkeypatch.setenv("BIN_FINDER_PROD_SUBTITLES", "false")
    config = ProductionConfig.load(tmp_path)
    assert config.speed == 0.8
    assert config.subtitles is False
    assert config.cache_dir == str(tmp_path / ".cache/production")


def test_bounded_speech_response():
    engine = VoiceStudioEngine(ProductionConfig())

    class FakeResponse(BytesIO):
        pass

    class FakeOpener:
        def open(self, *arguments, **keywords):
            return FakeResponse(b"too much data")

    engine.opener = FakeOpener()
    with pytest.raises(ProductionError, match="size limit"):
        engine._post("/v1/audio/speech", b"{}", "application/json", 4)


def test_transcribe_multipart_and_schema():
    import json
    engine = VoiceStudioEngine(ProductionConfig())
    requests = []

    class FakeOpener:
        def open(self, request, **keywords):
            requests.append(request)
            return BytesIO(json.dumps(dict(words=[dict(word="Hello", start=0, end=1)])).encode())

    engine.opener = FakeOpener()
    assert engine.transcribe(fake_wav()) == [WordStamp("Hello", 0, 1)]
    payload = requests[0].data
    assert b'timestamp_granularities[]' in payload
    assert b'whisper-1' in payload
    assert b'RIFF' in payload
