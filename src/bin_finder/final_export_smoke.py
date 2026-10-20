"""Bounded, offline real-FFmpeg acceptance. All media lives in temporary storage."""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.clips.extractor import FfmpegClipExtractor
from bin_finder.final_export import FORMAT, ExportOptions, FinalExportService
from bin_finder.integration_adapter import FORMAT as ADAPTER_FORMAT
from bin_finder.models import SceneRecord, SelectedClipRecord


def _run(command):
    result = subprocess.run(command, capture_output=True, timeout=60, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("FFmpeg smoke command failed")


def run_smoke():
    extractor = FfmpegClipExtractor(timeout=60)
    if not extractor.executable or not shutil.which(extractor.executable):
        print("SKIPPED_NO_FFMPEG")
        return 2
    repository = Path(__file__).resolve().parents[2]
    temp_parent = Path(tempfile.gettempdir()).resolve()
    if temp_parent == repository or repository in temp_parent.parents:
        raise RuntimeError("Smoke temporary storage must be outside the repository")
    with tempfile.TemporaryDirectory(prefix="bin-finder-f015-", dir=temp_parent) as directory:
        temporary = Path(directory)
        for source_id, color, duration in (("A", "blue", 36), ("B", "green", 6)):
            _run([extractor.executable, "-hide_banner", "-nostdin", "-n", "-f", "lavfi",
                  "-i", f"color=c={color}:s=160x90:r=10", "-t", str(duration),
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", str(temporary / f"{source_id}.mp4")])
        scenes, selections = [], []
        for i, (source_id, start) in enumerate((("A", 10.0), ("B", 0.0), ("A", 30.0)), 1):
            source = temporary / f"{source_id}.mp4"
            scene = SceneRecord(f"scene_{i:03d}", i, "Synthetic offline fixture", target_duration=20)
            scenes.append(scene)
            selections.append(SelectedClipRecord(f"clip_{i}", scene.scene_id, i, "local",
                source_id, "Synthetic fixture", str(source), start, start + 5, 5, .9, .9, .9,
                "owned", source_metadata={"media_sha256": fingerprint_file(source).sha256,
                                          "license_basis": "synthetic test media"}))
        destination = temporary / "library"
        service = FinalExportService(extractor=extractor)
        result = service.export("F015_OFFLINE_SMOKE", scenes, selections, destination,
                                ExportOptions(integration_adapter=True))
        assert result.status == "success", result.error
        assert result.readiness.ready and result.exported_count == 3
        manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
        assert manifest["format"] == FORMAT and manifest["readiness"]["ready"]
        assert [row["original_source_start_seconds"] for row in manifest["clips"]] == [10, 0, 30]
        assert [row["original_source_end_seconds"] for row in manifest["clips"]] == [15, 5, 35]
        for path, row in zip(result.clip_paths, manifest["clips"]):
            assert path.is_file() and path.stat().st_size > 0
            assert fingerprint_file(path).sha256 == row["exported_file_sha256"]
            assert row["original_source_media_sha256"]
            _run([extractor.executable, "-hide_banner", "-nostdin", "-v", "error",
                  "-i", str(path), "-f", "null", "-"])
        with result.csv_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert [r["filename"] for r in rows] == [p.name for p in result.clip_paths]
        adapter = json.loads(result.adapter_paths[0].read_text(encoding="utf-8"))
        assert adapter["format"] == ADAPTER_FORMAT and adapter["ready"]
        for scene, clip, path in zip(adapter["scenes"], selections, result.clip_paths):
            footage = scene["footage"]
            assert footage["source_id"] == clip.source_id
            assert Path(footage["path"]) == path
            assert footage["source_start_seconds"] == 0
            assert footage["source_end_seconds"] == footage["duration_seconds"] == 5
        assert json.loads(result.adapter_paths[1].read_text(encoding="utf-8"))["ready"]
        original_manifest = result.manifest_path.read_bytes()
        second = service.export("F015_OFFLINE_SMOKE", scenes, selections, destination)
        assert second.status == "failed" and second.error == "destination-exists"
        assert result.manifest_path.read_bytes() == original_manifest
        assert not list(temporary.glob(".bin-finder-export-partial-*"))
    assert not temporary.exists()
    print("PASS_F015_REAL_FFMPEG: 3 scenes A-B-A; MP4/manifest/CSV/materialized adapter; no overwrite; cleanup")
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
        print(f"FAILED_F015_REAL_FFMPEG: {type(error).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
