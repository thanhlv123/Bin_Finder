"""Bounded, offline F017 acceptance: F014 selections -> F010 READY -> real F015 export -> handoff.

All media lives in temporary storage outside the repository. Reuses the F015 A-B-A
fixture; F017 only verifies, moves and tampers with the produced package.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from bin_finder.acceptance import evaluate_project
from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.clips.extractor import FfmpegClipExtractor
from bin_finder.final_export import ExportOptions, FinalExportService
from bin_finder.final_selection import build_final_project
from bin_finder.handoff import FORMAT, HANDOFF_FILENAME, HandoffError, verify_handoff_package
from bin_finder.models import SceneRecord, SelectedClipRecord

PROJECT_ID = "F017_OFFLINE_SMOKE"
PLAN = (("A", 10.0), ("B", 0.0), ("A", 30.0))


def _run(command):
    result = subprocess.run(command, capture_output=True, timeout=60, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("FFmpeg smoke command failed")


def _expect_failure(path, *codes):
    try:
        verify_handoff_package(path)
    except HandoffError as error:
        assert error.code in codes, error.code
        return error.code
    raise AssertionError("verifier unexpectedly passed")


def export_package(executable, directory, name="library"):
    """Create synthetic A/B media, explicit selections, and a real F015+F017 export."""
    directory = Path(directory)
    for source_id, color, duration in (("A", "blue", 36), ("B", "green", 6)):
        _run([executable, "-hide_banner", "-nostdin", "-n", "-f", "lavfi",
              "-i", f"color=c={color}:s=160x90:r=10", "-t", str(duration),
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(directory / f"{source_id}.mp4")])
    scenes, selections = [], []
    for i, (source_id, start) in enumerate(PLAN, 1):
        source = directory / f"{source_id}.mp4"
        scene = SceneRecord(f"scene_{i:03d}", i, "Synthetic offline fixture", target_duration=20)
        scenes.append(scene)
        selections.append(SelectedClipRecord(f"clip_{i}", scene.scene_id, i, "local",
            source_id, "Synthetic fixture", str(source), start, start + 5, 5, .9, .9, .9,
            "owned", creator="Synthetic creator",
            source_metadata={"media_sha256": fingerprint_file(source).sha256,
                             "license_basis": "synthetic test media"}))
    destination = directory / name
    assert evaluate_project(build_final_project(PROJECT_ID, scenes, selections, destination)).ready
    service = FinalExportService(extractor=FfmpegClipExtractor(executable=executable, timeout=60))
    result = service.export(PROJECT_ID, scenes, selections, destination, ExportOptions(handoff=True))
    assert result.status == "success", result.error
    assert result.readiness.ready and result.handoff_path == destination / HANDOFF_FILENAME
    return destination, selections


def run_chain(executable, directory):
    directory = Path(directory)
    package, selections = export_package(executable, directory)
    handoff = json.loads((package / HANDOFF_FILENAME).read_text(encoding="utf-8"))
    assert handoff["format"] == FORMAT and handoff["ready"] and handoff["clip_count"] == 3
    # Original coordinates stay traceable; the files are independent trimmed clips.
    footage = [scene["footage"] for scene in handoff["scenes"]]
    assert [f["original_source_start_seconds"] for f in footage] == [10, 0, 30]
    assert [f["original_source_end_seconds"] for f in footage] == [15, 5, 35]
    assert [f["relative_path"] for f in footage] == [f"footage/scene_{i:03d}.mp4" for i in (1, 2, 3)]
    assert [f["source_id"] for f in footage] == ["A", "B", "A"]
    assert all(f["duration_seconds"] == 5 for f in footage)
    assert str(directory).lower() not in json.dumps(handoff).lower()
    report = verify_handoff_package(package)
    assert report.clip_count == 3 and report.total_duration_seconds == 15
    for path in report.clip_paths:
        _run([executable, "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-f", "null", "-"])

    moved = directory / "moved" / "renamed_package"
    moved.parent.mkdir()
    package.rename(moved)
    assert not package.exists()
    assert verify_handoff_package(moved).clip_count == 3

    victim = moved / "footage" / "scene_002.mp4"
    original = victim.read_bytes()
    victim.write_bytes(original + b"tamper")
    _expect_failure(moved, "byte-count-mismatch")
    victim.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    _expect_failure(moved, "sha256-mismatch")
    victim.write_bytes(original)
    assert verify_handoff_package(moved).clip_count == 3
    victim.unlink()
    _expect_failure(moved, "file-missing")

    fresh, _ = export_package(executable, directory, "library-2")
    assert verify_handoff_package(fresh).clip_count == 3
    (fresh / "footage" / "scene_003.mp4").unlink()
    _expect_failure(fresh, "file-missing")
    return selections


def run_smoke():
    extractor = FfmpegClipExtractor(timeout=60)
    if not extractor.executable or not shutil.which(extractor.executable):
        print("SKIPPED_NO_FFMPEG")
        return 2
    repository = Path(__file__).resolve().parents[2]
    temp_parent = Path(tempfile.gettempdir()).resolve()
    if temp_parent == repository or repository in temp_parent.parents:
        raise RuntimeError("Smoke temporary storage must be outside the repository")
    with tempfile.TemporaryDirectory(prefix="bin-finder-f017-", dir=temp_parent) as directory:
        temporary = Path(directory)
        run_chain(extractor.executable, temporary)
        assert not list(temporary.glob(".bin-finder-export-partial-*"))
    assert not temporary.exists()
    print("PASS_F017_REAL_HANDOFF: A-B-A export -> handoff verified -> package moved and verified "
          "-> tampered MP4 fails -> missing MP4 fails; cleanup")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approve-test-export", action="store_true")
    arguments = parser.parse_args(argv)
    if not arguments.approve_test_export:
        print("SKIPPED_NOT_APPROVED")
        return 0
    try:
        return run_smoke()
    except Exception as error:
        print(f"FAILED_F017_REAL_HANDOFF: {type(error).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
