"""Production verifier construction: real local VLM with a heuristic fallback per unit.

Building a verifier performs no network or FFmpeg work; requests happen only inside
``rerank()``, which the workflow runs on its worker thread.
"""
from __future__ import annotations

import os

from bin_finder.verification.ollama_vlm import (
    OllamaVisionVerifier, VlmConfig, VlmConfigError, config_from_env,
)
from bin_finder.verification.providers import HeuristicContextVerifier, VerificationProvider
from bin_finder.verification.reranker import VerificationReranker


class FallbackVerificationProvider:
    """Primary result per unit when usable, otherwise the fallback result for that unit only.

    Always returns exactly one entry per requested unit, in input order. Each result keeps
    the ``provider`` of whoever actually produced it.
    """

    def __init__(self, primary: VerificationProvider, fallback: VerificationProvider):
        self.primary, self.fallback = primary, fallback
        self.name = f"{primary.name}+fallback:{fallback.name}"

    def verify(self, scene, units):
        units = list(units)
        try:
            primary = list(self.primary.verify(scene, units))
        except Exception:
            primary = []
        results = [
            primary[i] if i < len(primary) and primary[i] is not None
            and primary[i].unit_id == unit.unit_id else None
            for i, unit in enumerate(units)]
        missing = [i for i, result in enumerate(results) if result is None]
        if missing:
            try:
                fallback = list(self.fallback.verify(scene, [units[i] for i in missing]))
            except Exception:
                fallback = []
            for slot, index in enumerate(missing):
                if slot < len(fallback) and fallback[slot] is not None \
                        and fallback[slot].unit_id == units[index].unit_id:
                    results[index] = fallback[slot]
        return results


def production_verifier(environ=None) -> VerificationReranker | None:
    """Verifier for the production workflow.

    mode ``auto`` (default): local Ollama VLM per unit, heuristic fallback per unit.
    mode ``heuristic``: text-only heuristic, never contacts Ollama.
    mode ``off``: ``None`` (historical behavior; F014 prepares with its own heuristic).
    An invalid mode/endpoint/model never sends frames anywhere and degrades to ``heuristic``.
    """
    environ = os.environ if environ is None else environ
    try:
        config = config_from_env(environ)
    except VlmConfigError:
        return VerificationReranker(HeuristicContextVerifier())
    if config.mode == "off":
        return None
    if config.mode == "heuristic":
        return VerificationReranker(HeuristicContextVerifier())
    return VerificationReranker(FallbackVerificationProvider(
        OllamaVisionVerifier(config), HeuristicContextVerifier()))
