"""Bounded, offline F016 acceptance: restore -> revalidate -> F010 READY -> real F015 export.

All media, sessions and exports live in temporary storage outside the repository.
The chain reuses F014 build_final_project, F010 evaluate_project and the F015
FinalExportService unchanged; nothing here grants a new approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from bin_finder.acceptance import evaluate_project
from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.clips.extractor import FfmpegClipExtractor
from bin_finder.final_export import FORMAT, ExportOptions, FinalExportService
from bin_finder.final_selection import build_final_project
from bin_finder.integration_adapter import FORMAT as ADAPTER_FORMAT
from bin_finder.models import SceneRecord, SelectedClipRecord
from bin_finder.session_codec import FORMAT as SESSION_FORMAT, scene_to_data, selection_to_data
from bin_finder.session_recovery import restore_session
from bin_finder.session_store import SessionStore

PROJECT_ID = "F016_OFFLINE_SMOKE"
# Original source coordinates for an A-B-A fixture (F015 smoke parity).
PLAN = (("A", 10.0), ("B", 0.0), ("A", 30.0))


def _run(command):
    result = subprocess.run(command, capture_output=True, timeout=60, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("FFmpeg smoke command failed")


def make_source(executable, path, color, duration):
    _run([executable, "-hide_banner", "-nostdin", "-n", "-f", "lavfi",
          "-i", f"color=c={color}:s=160x90:r=10", "-t", str(duration),
          "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])


def save_fixture_session(executable, directory):
    """Write synthetic sources and an explicitly approved F014-shaped session."""
    directory = Path(directory)
    make_source(executable, directory / "A.mp4", "blue", 36)
    make_source(executable, directory / "B.mp4", "green", 6)
    scenes, selections = [], []
    for i, (source_id, start) in enumerate(PLAN, 1):
        source = directory / f"{source_id}.mp4"
        scene = SceneRecord(f"scene_{i:03d}", i, "Synthetic offline fixture", target_duration=20)
        clip_id = "clip_" + hashlib.sha256(f"{scene.scene_id}:{source_id}:{start}".encode()).hexdigest()
        scenes.append(scene)
        selections.append(SelectedClipRecord(clip_id, scene.scene_id, i, "local",
            source_id, "Synthetic fixture", str(source), start, start + 5, 5, .9, .9, .9,
            "owned", source_metadata={"media_sha256": fingerprint_file(source).sha256,
                                      "license_basis": "synthetic test media"}))
    store = SessionStore(directory / "sessions")
    store.save({
        "format": SESSION_FORMAT, "project_id": PROJECT_ID,
        "scenes": [scene_to_data(scene) for scene in scenes],
        "final_selections": [selection_to_data(clip) for clip in selections],
        "workflow_refs": [],
        "ui_state": {"script_text": "Synthetic offline fixture",
                     "output_dir": str(directory / "library"),
                     "current_scene_id": scenes[0].scene_id},
    })
    return store, scenes, selections


def restore_ready(store, destination):
    """Simulated restart: a fresh store reads the active snapshot from disk."""
    restored = restore_session(SessionStore(store.root).load_active())
    project = build_final_project(restored.project_id, restored.scenes,
                                  restored.final_selections, destination)
    return restored, evaluate_project(project)


def verify_export(executable, result, selections):
    assert result.status == "success", result.error
    assert result.readiness.ready and result.exported_count == len(PLAN)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == FORMAT and manifest["readiness"]["ready"]
    # Readiness and provenance stay in original source coordinates.
    assert [row["original_source_start_seconds"] for row in manifest["clips"]] == [10, 0, 30]
    assert [row["original_source_end_seconds"] for row in manifest["clips"]] == [15, 5, 35]
    for path, row, clip in zip(result.clip_paths, manifest["clips"], selections):
        assert path.is_file() and path.stat().st_size > 0
        assert fingerprint_file(path).sha256 == row["exported_file_sha256"]
        assert row["original_source_media_sha256"] == clip.source_metadata["media_sha256"]
        _run([executable, "-hide_banner", "-nostdin", "-v", "error",
              "-i", str(path), "-f", "null", "-"])
    adapter = json.loads(result.adapter_paths[0].read_text(encoding="utf-8"))
    assert adapter["format"] == ADAPTER_FORMAT and adapter["ready"]
    # Materialized exported clips use local 0 -> duration coordinates.
    for scene, clip, path in zip(adapter["scenes"], selections, result.clip_paths):
        footage = scene["footage"]
        assert footage["source_id"] == clip.source_id
        assert Path(footage["path"]) == path
        assert footage["source_start_seconds"] == 0
        assert footage["source_end_seconds"] == footage["duration_seconds"] == 5
    return manifest


def run_chain(executable, directory):
    directory = Path(directory)
    store, _scenes, selections = save_fixture_session(executable, directory)
    destination = directory / "library"
    restored, report = restore_ready(store, destination)
    assert restored.unresolved == () and len(restored.final_selections) == len(PLAN)
    assert [c.clip_id for c in restored.final_selections] == [c.clip_id for c in selections]
    assert all(c.source_url == "" for c in restored.final_selections)
    assert report.ready, report.to_dict()
    service = FinalExportService(extractor=FfmpegClipExtractor(executable=executable, timeout=60))
    result = service.export(restored.project_id, restored.scenes, restored.final_selections,
                            destination, ExportOptions(integration_adapter=True))
    verify_export(executable, result, selections)
    # A source changed after the session was saved is never re-approved.
    make_source(executable, directory / "B2.mp4", "red", 6)
    shutil.copyfile(directory / "B2.mp4", directory / "B.mp4")
    tampered, tampered_report = restore_ready(store, directory / "library-2")
    assert tampered.unresolved == (("scene_002", "media-identity-changed"),)
    assert not tampered_report.ready
    refused = service.export(tampered.project_id, tampered.scenes, tampered.final_selections,
                             directory / "library-2")
    assert refused.status == "not_ready" and not (directory / "library-2").exists()
    return result


def run_smoke():
    extractor = FfmpegClipExtractor(timeout=60)
    if not extractor.executable or not shutil.which(extractor.executable):
        print("SKIPPED_NO_FFMPEG")
        return 2
    repository = Path(__file__).resolve().parents[2]
    temp_parent = Path(tempfile.gettempdir()).resolve()
    if temp_parent == repository or repository in temp_parent.parents:
        raise RuntimeError("Smoke temporary storage must be outside the repository")
    with tempfile.TemporaryDirectory(prefix="bin-finder-f016-", dir=temp_parent) as directory:
        temporary = Path(directory)
        run_chain(extractor.executable, temporary)
        assert not list(temporary.glob(".bin-finder-export-partial-*"))
    assert not temporary.exists()
    print("PASS_F016_RESTORE_EXPORT: session restore -> SHA-256 revalidation -> F010 READY "
          "-> real F015 A-B-A export; tampered source unresolved/not_ready; cleanup")
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
        print(f"FAILED_F016_RESTORE_EXPORT: {type(error).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
