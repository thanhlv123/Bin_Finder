"""PCM silence insertion and exact timestamp movement."""
from array import array
from io import BytesIO
import wave

import pytest

from bin_finder.production import ProductionError
from bin_finder.production.pauses import add_punctuation_pauses, quietest_frame
from bin_finder.production.tts import WordStamp, wav_duration, wav_info


def tone_wav(channels=1, sample_width=2):
    samples = array("h", [1200] * 8000 * channels)
    for index in range(2500 * channels, 4500 * channels):
        samples[index] = 0
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(sample_width)
        audio.setframerate(8000)
        audio.writeframes(samples.tobytes())
    return output.getvalue()


@pytest.mark.parametrize("channels", [1, 2])
def test_pauses_length_shift_and_last_word(channels):
    words = [WordStamp("Hello,", 0, 0.3), WordStamp("there.", 0.6, 0.7), WordStamp("End!", 0.8, 1)]
    audio, shifted = add_punctuation_pauses(tone_wav(channels), words, 0.25, 0.5)
    assert wav_duration(audio) == 1.75
    assert shifted[0] == words[0]
    assert shifted[1].start == pytest.approx(0.85)
    assert shifted[2].start == pytest.approx(1.55)
    assert shifted[2].end == pytest.approx(1.75)
    assert words[1].start == 0.6


def test_quiet_window():
    parameters, raw = wav_info(tone_wav())
    samples = array("h")
    samples.frombytes(raw)
    frame = quietest_frame(samples, 1, parameters.framerate, 0.3, 0.6)
    assert 2500 <= frame <= 4500
    assert samples[frame] == 0


def test_unsupported_pcm():
    with pytest.raises(ProductionError, match="16-bit PCM"):
        add_punctuation_pauses(tone_wav(sample_width=1), [], 0.25, 0.5)
