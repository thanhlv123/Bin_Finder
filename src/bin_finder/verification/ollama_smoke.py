"""Explicit opt-in live check against a LOCAL Ollama vision model. Never runs in pytest/CI.

Nothing is downloaded, installed or pulled. A tiny synthetic clip is generated in temporary
storage, one real frame set is sent to the loopback Ollama endpoint, and the structured
result is validated.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from bin_finder.models import SceneContext, SceneRecord
from bin_finder.retrieval.models import RetrievalUnit
from bin_finder.verification.ollama_vlm import (
    OllamaVisionVerifier, VlmConfigError, config_from_env,
)


def _ffmpeg() -> str:
    return os.environ.get("BIN_FINDER_FFMPEG", "").strip() or shutil.which("ffmpeg") or ""


def run_smoke() -> int:
    try:
        config = config_from_env(os.environ)
    except VlmConfigError as error:
        print(f"FAILED_F021_REAL_VLM: invalid configuration ({error})")
        return 2
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        print("FAILED_F021_REAL_VLM: FFmpeg not found")
        return 2
    repository = Path(__file__).resolve().parents[3]
    temp_parent = Path(tempfile.gettempdir()).resolve()
    if temp_parent == repository or repository in temp_parent.parents:
        raise RuntimeError("Smoke temporary storage must be outside the repository")
    with tempfile.TemporaryDirectory(prefix="bin-finder-f021-", dir=temp_parent) as directory:
        clip = Path(directory) / "red.mp4"
        made = subprocess.run(
            [ffmpeg, "-hide_banner", "-nostdin", "-n", "-f", "lavfi", "-i",
             "color=c=red:s=320x180:r=10", "-t", "4", "-c:v", "libx264", "-pix_fmt", "yuv420p",
             str(clip)], capture_output=True, timeout=60, check=False)
        if made.returncode:
            print("FAILED_F021_REAL_VLM: could not create the synthetic clip")
            return 2
        scene = SceneRecord("scene_001", 1, "A plain solid red screen.",
                            context=SceneContext(objects=("red screen",), avoid=("people",)))
        unit = RetrievalUnit("smoke_unit", str(clip), 0.0, 4.0)
        verifier = OllamaVisionVerifier(config)
        result = verifier.verify(scene, [unit])[0]
        if result is None:
            print(f"FAILED_F021_REAL_VLM: no valid structured result from {verifier.name} "
                  f"at {config.url} (is Ollama running and the model pulled?)")
            return 1
        print(f"PASS_F021_REAL_VLM: {result.provider} confidence={result.confidence:.2f}")
        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-live-vlm", action="store_true")
    arguments = parser.parse_args(argv)
    if not arguments.approve_live_vlm:
        print("SKIPPED_NOT_APPROVED")
        return 0
    try:
        return run_smoke()
    except Exception as error:
        print(f"FAILED_F021_REAL_VLM: {type(error).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
