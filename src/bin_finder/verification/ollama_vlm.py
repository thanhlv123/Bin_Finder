"""Local Ollama vision verifier (stdlib HTTP, loopback only). Implements VerificationProvider."""
from __future__ import annotations

import base64
import json
import math
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

from bin_finder.models import SceneRecord
from bin_finder.retrieval.models import RetrievalUnit
from bin_finder.verification.frame_sampler import (
    FfmpegFrameSampler, FrameSamplingError, FrameSamplingPolicy,
)
from bin_finder.verification.models import VerificationDimensions, VerificationResult

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen3-vl:4b"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_NUM_CTX = 8192
DEFAULT_NUM_PREDICT = 2048
NUM_CTX_RANGE = (2048, 32768)
NUM_PREDICT_RANGE = (128, 8192)
MAX_RESPONSE_BYTES = 1_048_576
MAX_EXPLANATION_CHARS = 300
DIMENSIONS = ("subject_match", "action_match", "location_match", "object_match",
              "time_match", "visual_quality", "context_conflict")
_MODEL = re.compile(r"[A-Za-z0-9._:/-]{1,100}")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _int_between(value, low, high) -> bool:
    return type(value) is int and low <= value <= high


class VlmConfigError(ValueError):
    """Invalid VLM configuration; frames are never sent with an invalid endpoint."""


class VlmUnavailable(Exception):
    """Transport/server-level failure: skip remaining units of this verify() call."""


class VlmResponseError(Exception):
    """This unit's response was unusable; other units are unaffected."""


@dataclass(frozen=True)
class VlmConfig:
    mode: str = "auto"
    model: str = DEFAULT_MODEL
    url: str = DEFAULT_URL
    timeout: float = 120.0
    frames: int = 3
    # The default model is a Thinking build: 3 frames use ~3.3k prompt tokens, so Ollama's 4096
    # default window is exhausted before the JSON answer is written (real-footage finding).
    num_ctx: int = DEFAULT_NUM_CTX
    num_predict: int = DEFAULT_NUM_PREDICT

    def validate(self) -> None:
        if self.mode not in {"auto", "heuristic", "off"}:
            raise VlmConfigError("invalid-mode")
        if not _MODEL.fullmatch(self.model):
            raise VlmConfigError("invalid-model")
        if not (isinstance(self.timeout, (int, float)) and math.isfinite(self.timeout)
                and 1 <= self.timeout <= 600):
            raise VlmConfigError("invalid-timeout")
        if not 1 <= self.frames <= FrameSamplingPolicy().max_frames:
            raise VlmConfigError("invalid-frames")
        if not _int_between(self.num_ctx, *NUM_CTX_RANGE):
            raise VlmConfigError("invalid-num-ctx")
        if not _int_between(self.num_predict, *NUM_PREDICT_RANGE) or self.num_predict >= self.num_ctx:
            raise VlmConfigError("invalid-num-predict")
        validate_loopback_url(self.url)


def validate_loopback_url(url: str) -> str:
    """Only http://<loopback>[:port] is accepted: no credentials, path, query or fragment."""
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise VlmConfigError("invalid-url") from None
    if (parts.scheme != "http" or host not in LOOPBACK_HOSTS or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment
            or parts.path not in ("", "/")):
        raise VlmConfigError("non-loopback-or-invalid-url")
    netloc = f"[{host}]" if ":" in host else host
    return f"http://{netloc}" + (f":{port}" if port else "")


def config_from_env(environ) -> VlmConfig:
    """No secrets are read. Unset values use defaults; invalid ones raise VlmConfigError."""
    def get(name, default):
        value = (environ.get(name) or "").strip()
        return value or default
    try:
        timeout = float(get("BIN_FINDER_VLM_TIMEOUT_SECONDS", 120))
        frames = int(get("BIN_FINDER_VLM_FRAMES_PER_UNIT", 3))
        num_ctx = int(get("BIN_FINDER_VLM_NUM_CTX", DEFAULT_NUM_CTX))
        num_predict = int(get("BIN_FINDER_VLM_NUM_PREDICT", DEFAULT_NUM_PREDICT))
    except ValueError:
        raise VlmConfigError("invalid-number") from None
    config = VlmConfig(mode=get("BIN_FINDER_VLM_MODE", "auto").lower(),
                       model=get("BIN_FINDER_VLM_MODEL", DEFAULT_MODEL),
                       url=get("BIN_FINDER_OLLAMA_URL", DEFAULT_URL),
                       timeout=timeout, frames=frames, num_ctx=num_ctx, num_predict=num_predict)
    config.validate()
    return config


def _score(value, *, required=False):
    if value is None:
        if required:
            raise VlmResponseError("missing-score")
        return None
    if type(value) not in (int, float) or not math.isfinite(value):
        raise VlmResponseError("invalid-score")
    # F005 clamps; F021 rejects instead so a 0-100 answer cannot masquerade as 1.0.
    if value < -1e-9 or value > 1 + 1e-9:
        raise VlmResponseError("score-out-of-range")
    return float(min(1.0, max(0.0, value)))


def parse_vlm_response(text: str, unit_id: str, provider: str) -> VerificationResult:
    """Strict JSON-object parser; raises VlmResponseError for anything unusable."""
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_RESPONSE_BYTES:
        raise VlmResponseError("empty-or-oversized")
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        data = json.loads(body, parse_constant=lambda _name: (_ for _ in ()).throw(ValueError()))
    except (ValueError, RecursionError):
        raise VlmResponseError("malformed-json") from None
    if not isinstance(data, dict):
        raise VlmResponseError("not-an-object")
    dimensions = {name: _score(data.get(name)) for name in DIMENSIONS}
    if all(value is None for value in dimensions.values()):
        raise VlmResponseError("no-dimensions")
    confidence = _score(data.get("confidence"), required=True)
    explanation = data.get("explanation", "")
    explanation = _CONTROL.sub(" ", explanation) if isinstance(explanation, str) else ""
    return VerificationResult(
        unit_id=unit_id, provider=provider, dimensions=VerificationDimensions(**dimensions),
        confidence=confidence,
        explanation=" ".join(explanation.split())[:MAX_EXPLANATION_CHARS]).normalized()


def _items(values, limit=8):
    return [str(v)[:100] for v in list(values)[:limit]]


def build_prompt(scene: SceneRecord, unit: RetrievalUnit, frame_count: int) -> str:
    c = scene.context
    context = {
        "script": scene.english_text[:1500], "subject": _items(c.subject),
        "action": _items(c.action), "location": _items(c.location),
        "objects": _items(c.objects), "mood": _items(c.mood), "avoid": _items(c.avoid),
        "segment_start_seconds": round(unit.start, 3), "segment_end_seconds": round(unit.end, 3),
    }
    return (
        f"You are verifying stock footage. The {frame_count} attached images are frames sampled "
        "in time order from ONE video segment. Judge ONLY what is visible in the images against "
        "this requested scene:\n" + json.dumps(context, ensure_ascii=False) + "\n"
        "Reply with a single JSON object and nothing else, with these keys: subject_match, "
        "action_match, location_match, object_match, time_match, visual_quality, context_conflict "
        "(each a number from 0 to 1, or null if it cannot be judged from the images; "
        "context_conflict is 1 when the frames show something listed in avoid), confidence "
        "(0 to 1), explanation (one short sentence)."
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class OllamaVisionVerifier:
    """VerificationProvider that sends sampled frames to a local Ollama vision model."""

    def __init__(self, config: VlmConfig | None = None, sampler=None, opener=None):
        self.config = config or VlmConfig()
        self.config.validate()
        self.base_url = validate_loopback_url(self.config.url)
        self.name = f"ollama-vlm:{self.config.model}"
        self.sampler = sampler or FfmpegFrameSampler(
            policy=FrameSamplingPolicy(frames=self.config.frames))
        # No system proxy and no redirects: loopback traffic stays on loopback.
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect())

    def verify(self, scene: SceneRecord, units) -> list[VerificationResult | None]:
        results: list[VerificationResult | None] = []
        unavailable = False
        for unit in units:
            if unavailable:
                results.append(None)
                continue
            try:
                results.append(self._verify_unit(scene, unit))
            except VlmUnavailable:
                unavailable = True  # do not wait through every remaining unit
                results.append(None)
            except (FrameSamplingError, VlmResponseError):
                results.append(None)
            except Exception:
                results.append(None)
        return results

    def _verify_unit(self, scene, unit) -> VerificationResult:
        frames = self.sampler.sample(unit.source_path, unit.start, unit.end)
        content = self._chat(scene, unit, frames)
        return parse_vlm_response(content, unit.unit_id, self.name)

    def _chat(self, scene, unit, frames) -> str:
        payload = {
            "model": self.config.model, "stream": False, "format": "json",
            "options": {"temperature": 0, "seed": 0, "num_ctx": self.config.num_ctx,
                        "num_predict": self.config.num_predict},
            "messages": [{
                "role": "user", "content": build_prompt(scene, unit, len(frames)),
                "images": [base64.b64encode(frame).decode("ascii") for frame in frames]}],
        }
        request = urllib.request.Request(
            self.base_url + "/api/chat", data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self.opener.open(request, timeout=self.config.timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, OSError, ValueError):
            raise VlmUnavailable() from None  # includes HTTP errors, timeouts, missing model
        if len(body) > MAX_RESPONSE_BYTES:
            raise VlmResponseError("oversized-response")
        try:
            content = json.loads(body.decode("utf-8"))["message"]["content"]
        except (ValueError, KeyError, TypeError):
            raise VlmResponseError("malformed-envelope") from None
        if not isinstance(content, str):
            raise VlmResponseError("malformed-envelope")
        return content
