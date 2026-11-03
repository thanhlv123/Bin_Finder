"""Bounded loopback speech, word alignment and reusable raw speech cache."""
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
import re
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4
import wave

from . import ProductionError
from .config import ProductionConfig


@dataclass(frozen=True)
class WordStamp:
    word: str
    start: float
    end: float


class SpeechEngine(Protocol):
    def synthesize(self, text: str) -> bytes:
        """Return PCM WAV speech."""
        ...

    def transcribe(self, wav_bytes: bytes) -> list[WordStamp]:
        """Return word timestamps in seconds."""
        ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request: Request, response: object, code: int,
                         message: str, headers: object, new_url: str) -> None:
        """Reject every redirect, including redirects away from loopback."""
        return None


def wav_info(wav_bytes: bytes) -> tuple[wave._wave_params, bytes]:
    """Validate the supported PCM format and return samples."""
    try:
        with wave.open(BytesIO(wav_bytes), "rb") as audio:
            parameters = audio.getparams()
            samples = audio.readframes(audio.getnframes())
    except (wave.Error, EOFError) as error:
        raise ProductionError("Invalid PCM WAV response") from error
    if parameters.sampwidth != 2 or parameters.nchannels not in (1, 2) or parameters.comptype != "NONE":
        raise ProductionError("WAV must be 16-bit PCM mono or stereo")
    if not parameters.nframes or len(samples) != parameters.nframes * parameters.nchannels * 2:
        raise ProductionError("Empty or truncated WAV")
    return parameters, samples


def encode_wav(parameters: wave._wave_params, samples: bytes) -> bytes:
    """Encode PCM bytes with an updated WAV frame count."""
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams(parameters)
        audio.writeframes(samples)
    return output.getvalue()


def wav_duration(wav_bytes: bytes) -> float:
    """Return the exact sample duration."""
    parameters, _ = wav_info(wav_bytes)
    return parameters.nframes / parameters.framerate


class VoiceStudioEngine:
    def __init__(self, config: ProductionConfig) -> None:
        self.config = config
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def _post(self, endpoint: str, payload: bytes, content_type: str, limit: int) -> bytes:
        request = Request(self.config.tts_url.rstrip("/") + endpoint, payload,
                          {"Content-Type": content_type})
        try:
            with self.opener.open(request, timeout=self.config.tts_timeout_sec) as response:
                result = response.read(limit + 1)
        except HTTPError as error:
            raise ProductionError(f"VoiceStudio returned HTTP {error.code}") from None
        except (URLError, OSError, TimeoutError):
            raise ProductionError(f"VoiceStudio is not running at {self.config.tts_url}") from None
        if len(result) > limit:
            raise ProductionError("VoiceStudio response exceeds size limit")
        return result

    def synthesize(self, text: str) -> bytes:
        """Request bounded speech from the configured local voice."""
        payload = dict(model=self.config.tts_model, input=text, voice=self.config.voice,
                       speed=self.config.speed, response_format="wav", language=self.config.language,
                       seed=self.config.seed)
        result = self._post("/v1/audio/speech", json.dumps(payload).encode(),
                            "application/json", 128 * 1024 * 1024)
        wav_info(result)
        return result

    def transcribe(self, wav_bytes: bytes) -> list[WordStamp]:
        """Upload WAV as multipart data and validate word timestamps."""
        boundary = uuid4().hex
        parts = []
        for name, value in (("model", "whisper-1"), ("language", self.config.language),
                            ("response_format", "verbose_json"), ("timestamp_granularities[]", "word")):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode())
        parts.extend([wav_bytes, f"\r\n--{boundary}--\r\n".encode()])
        response = self._post("/v1/audio/transcriptions", b"".join(parts),
                              f"multipart/form-data; boundary={boundary}", 8 * 1024 * 1024)
        try:
            words = [WordStamp(str(item["word"]), float(item["start"]), float(item["end"]))
                     for item in json.loads(response).get("words", [])]
            if any(not math.isfinite(word.start) or not math.isfinite(word.end) or
                   word.start < 0 or word.end < word.start for word in words):
                raise ValueError
            return words
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProductionError("Invalid VoiceStudio word timestamps") from None


def align_words(script_text: str, asr_words: list[WordStamp], total_seconds: float) -> list[WordStamp]:
    """Match normalized words; interpolate unmatched runs by character weight."""
    tokens = script_text.split()
    normalize = lambda text: re.sub(r"[^\w]", "", text.casefold())
    anchors = {}
    matcher = SequenceMatcher(None, [normalize(token) for token in tokens],
                              [normalize(item.word) for item in asr_words], autojunk=False)
    previous_end = 0.0
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            stamp = asr_words[block.b + offset]
            start = min(total_seconds, max(previous_end, stamp.start))
            end = min(total_seconds, max(start, stamp.end))
            anchors[block.a + offset] = (start, end)
            previous_end = end
    result = []
    previous_index = -1
    previous_end = 0.0
    for next_index in [*anchors, len(tokens)]:
        next_start = anchors[next_index][0] if next_index in anchors else total_seconds
        weights = [max(1, len(token)) for token in tokens[previous_index + 1:next_index]]
        weight_total = sum(weights) or 1
        cursor = previous_end
        for token, weight in zip(tokens[previous_index + 1:next_index], weights):
            end = cursor + max(0, next_start - previous_end) * weight / weight_total
            result.append(WordStamp(token, cursor, end))
            cursor = end
        if next_index in anchors:
            start, end = anchors[next_index]
            result.append(WordStamp(tokens[next_index], start, end))
            previous_end = end
            previous_index = next_index
    return result


def cached_speech(text: str, engine: SpeechEngine, config: ProductionConfig) -> tuple[bytes, list[WordStamp]]:
    """Cache raw WAV and alignment; pauses are always applied afterwards."""
    identity = [text, config.voice, config.speed, config.tts_model, config.seed, config.language, config.tts_url]
    digest = sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
    directory = Path(config.cache_dir) / "tts"
    directory.mkdir(parents=True, exist_ok=True)
    audio_path = directory / f"{digest}.wav"
    words_path = directory / f"{digest}.json"
    if audio_path.exists() and words_path.exists():
        try:
            audio = audio_path.read_bytes()
            wav_info(audio)
            payload = json.loads(words_path.read_text(encoding="utf-8"))
            if payload["sha256"] == sha256(audio).hexdigest():
                return audio, [WordStamp(**item) for item in payload["words"]]
        except (ValueError, KeyError, TypeError, ProductionError):
            pass
    audio = engine.synthesize(text)
    words = align_words(text, engine.transcribe(audio), wav_duration(audio))
    temporary = audio_path.with_suffix(".wav.tmp")
    temporary.write_bytes(audio)
    temporary.replace(audio_path)
    temporary = words_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(dict(sha256=sha256(audio).hexdigest(), words=[asdict(item) for item in words])), encoding="utf-8")
    temporary.replace(words_path)
    return audio, words
