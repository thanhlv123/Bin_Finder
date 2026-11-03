"""Insert punctuation silence at quiet PCM windows using only stdlib."""
from array import array
from dataclasses import replace
import sys

from . import ProductionError
from .tts import WordStamp, encode_wav, wav_info


def quietest_frame(samples: array, channels: int, rate: int, start: float, end: float) -> int:
    """Find the lowest mean-square 20 ms window inside the word gap."""
    frame_count = len(samples) // channels
    first = min(frame_count, max(0, round(start * rate)))
    last = min(frame_count, max(first, round(end * rate)))
    window = min(max(1, rate // 50), last - first)
    if window <= 0:
        return first
    best_frame = first + window // 2
    best_energy = float("inf")
    for frame in range(first, last - window + 1, max(1, window // 2)):
        section = samples[frame * channels:(frame + window) * channels]
        energy = sum(value * value for value in section)
        if energy < best_energy:
            best_frame = frame + window // 2
            best_energy = energy
    return best_frame


def add_punctuation_pauses(wav_bytes: bytes, words: list[WordStamp], comma: float,
                           stop: float) -> tuple[bytes, list[WordStamp]]:
    """Insert silence after punctuation except the final word of a block."""
    if min(comma, stop) < 0:
        raise ProductionError("Pause durations must be nonnegative")
    parameters, raw = wav_info(wav_bytes)
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    cuts = []
    shifted = list(words)
    for index, stamp in enumerate(words[:-1]):
        tail = stamp.word.rstrip('"\'”’)]}')
        duration = stop if tail.endswith((".", "?", "!")) else comma if tail.endswith((",", ";", ":")) else 0
        if duration <= 0:
            continue
        position = quietest_frame(samples, parameters.nchannels, parameters.framerate,
                                  stamp.end, words[index + 1].start)
        frames = round(duration * parameters.framerate)
        cuts.append((position * parameters.nchannels * 2, frames * parameters.nchannels * 2))
        shift = frames / parameters.framerate
        for following in range(index + 1, len(words)):
            shifted[following] = replace(shifted[following], start=shifted[following].start + shift,
                                         end=shifted[following].end + shift)
    output = []
    cursor = 0
    for position, byte_count in sorted(cuts):
        output.extend([raw[cursor:position], bytes(byte_count)])
        cursor = position
    output.append(raw[cursor:])
    return encode_wav(parameters, b"".join(output)), shifted
