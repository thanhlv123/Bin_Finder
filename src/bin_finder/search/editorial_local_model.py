"""BF-S04A.1 research: bounded LOCAL Ollama text-to-editorial-shot proposal.

All outputs remain unverified human-review proposals. No providers, footage,
frame uploads, rights clearance, downloading, or timeline modification.
One model request maximum per explicit approval; no hidden retries/fallbacks.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Sequence

from bin_finder.models import SceneRecord
from bin_finder.search.editorial_shot_plan import (
    EditorialShotPlan, EditorialShotPlanError,
    FORMAT as EDITORIAL_PLAN_FORMAT, parse_editorial_shot_plan,
)
from bin_finder.search.editorial_shot_prompt import make_editorial_shot_prompt
from bin_finder.search.visual_search_contract import SemanticSearchPlan
from bin_finder.verification.ollama_vlm import _NoRedirect, validate_loopback_url

MAX_RESPONSE_BYTES = 262_144
_MODELS = frozenset({"qwen3-vl:4b-instruct", "qwen3-vl:4b"})


class LocalEditorialConfigError(ValueError):
    """Only fixed error labels; never a user path, prompt or HTTP URL."""


@dataclass(frozen=True)
class LocalEditorialConfig:
    model: str = "qwen3-vl:4b-instruct"
    url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 180.0
    num_ctx: int = 8192
    num_predict: int = 4096

    def validate(self) -> None:
        if self.model not in _MODELS:
            raise LocalEditorialConfigError("unsupported-local-text-model")
        if (type(self.timeout_seconds) not in (int, float)
                or not math.isfinite(self.timeout_seconds)
                or not 1 <= self.timeout_seconds <= 600):
            raise LocalEditorialConfigError("invalid-local-text-timeout")
        if (type(self.num_ctx) is not int or not 4096 <= self.num_ctx <= 32768
                or type(self.num_predict) is not int
                or not 256 <= self.num_predict <= 8192
                or self.num_predict >= self.num_ctx):
            raise LocalEditorialConfigError("invalid-local-text-budget")
        # F021 rejects remote hosts, HTTPS, credentials, ports with invalid syntax,
        # query strings and path escapes.
        validate_loopback_url(self.url)


@dataclass(frozen=True)
class LocalEditorialOutcome:
    status: str
    plan: EditorialShotPlan | None = None
    calls_attempted: int = 0
    confirmed_http_requests: str = "0"
    reject_reason: str = ""
    provider_calls: int = 0
    cloud_uploads: int = 0
    media_downloads: int = 0
    timeline_approved: bool = False


def _duplicate_guard(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate-keys")
        obj[key] = value
    return obj


def parse_local_editorial_reply(
    reply: str, base: SemanticSearchPlan, scenes: Sequence[SceneRecord],
) -> EditorialShotPlan:
    """One strictly bounded JSON object, then canonical editorial validator."""
    if not isinstance(reply, str) or not reply.strip():
        raise EditorialShotPlanError("empty-local-model-reply")
    if len(reply.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise EditorialShotPlanError("oversized-local-model-reply")
    try:
        candidate = json.loads(
            reply, object_pairs_hook=_duplicate_guard,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
        )
    except (ValueError, RecursionError):
        raise EditorialShotPlanError("invalid-local-model-json") from None
    if not isinstance(candidate, dict):
        raise EditorialShotPlanError("invalid-local-model-object")
    # The model may emit ONLY editorial shot rows. The trusted application
    # supplies immutable version/plan IDs/digest; it does not invent, correct
    # or authorize the model-generated visual choices or license claims.
    if set(candidate) == {"shots"}:
        candidate = {
            "format": EDITORIAL_PLAN_FORMAT,
            "plan_id": "bf_s04a_model_proposal",
            "base_plan_id": base.plan_id,
            "source_digest": base.source_digest,
            "shots": candidate["shots"],
        }
    # A legacy full wrapper remains fully validated; partial/forged wrappers
    # never get fixed up or silently blessed as authoritative.
    return parse_editorial_shot_plan(candidate, base, scenes)


class OllamaLocalEditorialPlanner:
    def __init__(self, config: LocalEditorialConfig | None = None, *, opener=None):
        self.config = config or LocalEditorialConfig()
        self.config.validate()
        self.base_url = validate_loopback_url(self.config.url)
        # Never let operating-system proxy environment or HTTP redirects turn
        # a loopback-only text request into a cloud request.
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect(),
        )

    def propose(
        self, base: SemanticSearchPlan, scenes: Sequence[SceneRecord], *,
        approve_local_model_call: bool = False,
    ) -> LocalEditorialOutcome:
        if type(approve_local_model_call) is not bool:
            raise LocalEditorialConfigError("invalid-local-model-approval")
        # Validate scene digest and bounded prompt even in dry-run mode, but
        # never initialize an outbound request without explicit approval.
        prompt = make_editorial_shot_prompt(base, scenes, shots_only=True)
        if not approve_local_model_call:
            return LocalEditorialOutcome("local-model-approval-required")

        payload = {
            "model": self.config.model, "stream": False, "format": "json",
            "options": {
                "temperature": 0, "seed": 0,
                "num_ctx": self.config.num_ctx,
                "num_predict": self.config.num_predict,
            },
            "messages": [{"role": "user", "content": prompt}],
        }
        request = urllib.request.Request(
            self.base_url + "/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener.open(
                request, timeout=self.config.timeout_seconds,
            ) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except (urllib.error.URLError, OSError, ValueError):
            return LocalEditorialOutcome(
                "local-model-unavailable", calls_attempted=1,
                confirmed_http_requests="unknown",
            )
        if len(body) > MAX_RESPONSE_BYTES:
            return LocalEditorialOutcome(
                "local-model-reply-oversized", calls_attempted=1,
                confirmed_http_requests="unknown",
            )
        try:
            envelope = json.loads(body.decode("utf-8"))
            reply = envelope["message"]["content"]
            if not isinstance(reply, str):
                raise ValueError()
        except (ValueError, KeyError, TypeError, UnicodeError):
            return LocalEditorialOutcome(
                "local-model-envelope-invalid", calls_attempted=1,
                confirmed_http_requests="unknown",
            )
        try:
            result = parse_local_editorial_reply(reply, base, scenes)
        except EditorialShotPlanError as exc:
            # Fixed error codes from the structural validator; raw model output
            # is never copied into report or app logs.
            return LocalEditorialOutcome(
                "local-model-shot-plan-rejected", calls_attempted=1,
                confirmed_http_requests="unknown", reject_reason=str(exc),
            )
        return LocalEditorialOutcome(
            "local-shot-plan-proposed-human-review", plan=result,
            calls_attempted=1, confirmed_http_requests="unknown",
        )
