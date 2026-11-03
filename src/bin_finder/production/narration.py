"""Synthesize contiguous cue blocks and retain exact cue word boundaries."""
from dataclasses import dataclass, field, replace
from typing import Callable

from . import ProductionError
from .config import ProductionConfig
from .pauses import add_punctuation_pauses
from .tts import SpeechEngine, WordStamp, cached_speech, encode_wav, wav_info


@dataclass
class Narration:
    wav_bytes: bytes
    words: list[WordStamp]
    cue_starts: dict[str, float]
    duration: float
    end_hold: float = 2.0
    cue_block_indices: dict[str, int] = field(default_factory=dict)


def cue_blocks(cues: list[dict], maximum: int) -> list[list[dict]]:
    """Keep every cue whole, including a single oversized cue."""
    blocks = []
    current = []
    for cue in cues:
        if not cue["text"].split():
            raise ProductionError(f"Empty narration cue: {cue['cue_id']}")
        if current and len(" ".join(item["text"] for item in [*current, cue])) > maximum:
            blocks.append(current)
            current = []
        current.append(cue)
    if current:
        blocks.append(current)
    return blocks


def build_narration(cues: list[dict], engine: SpeechEngine, config: ProductionConfig,
                    progress: Callable[[str], None] = print) -> Narration:
    """Combine paused blocks with silence only between blocks."""
    blocks = cue_blocks(cues, config.tts_block_max_chars)
    samples = []
    all_words = []
    cue_starts = {}
    cue_block_indices = {}
    parameters = None
    frame_offset = 0
    for block_index, block in enumerate(blocks):
        progress(f"TTS block {block_index + 1}/{len(blocks)}")
        audio, words = cached_speech(" ".join(cue["text"] for cue in block), engine, config)
        audio, words = add_punctuation_pauses(audio, words, config.comma_pause, config.stop_pause)
        current_parameters, raw = wav_info(audio)
        if parameters and current_parameters[:3] != parameters[:3]:
            raise ProductionError("VoiceStudio changed WAV format between blocks")
        parameters = current_parameters
        offset = frame_offset / parameters.framerate
        word_index = 0
        for cue in block:
            cue_block_indices[cue["cue_id"]] = block_index
            cue_starts[cue["cue_id"]] = words[word_index].start + offset
            word_index += len(cue["text"].split())
        all_words.extend(replace(word, start=word.start + offset, end=word.end + offset) for word in words)
        samples.append(raw)
        frame_offset += current_parameters.nframes
        if block_index < len(blocks) - 1:
            gap_frames = round(config.block_gap * parameters.framerate)
            samples.append(bytes(gap_frames * parameters.nchannels * 2))
            frame_offset += gap_frames
    if parameters is None:
        raise ProductionError("No narration cues")
    return Narration(encode_wav(parameters, b"".join(samples)), all_words, cue_starts,
                     frame_offset / parameters.framerate, config.end_hold, cue_block_indices)
