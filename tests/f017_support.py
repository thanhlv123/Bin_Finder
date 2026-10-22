"""Shared offline fixture for F017 tests: a real F015 export driven by a fake extractor."""
import json
from pathlib import Path
from types import SimpleNamespace

from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.clips.extractor import FfmpegClipExtractor
from bin_finder.clips.models import ExtractionResult
from bin_finder.final_export import ExportOptions, FinalExportService
from bin_finder.handoff import HANDOFF_FILENAME
from bin_finder.models import SceneRecord, SelectedClipRecord


class FakeExtractor(FfmpegClipExtractor):
    def __init__(self):
        super().__init__(executable="offline-ffmpeg")
        self.calls = []

    def extract(self, proposal, output_path, *, overwrite=False):
        self.calls.append(proposal)
        output_path.write_bytes(f"clip:{proposal.unit_id}".encode())
        return ExtractionResult(str(output_path), output_path.stat().st_size, proposal.duration)


def make_inputs(base: Path, **clip_overrides):
    sources = {}
    for name in ("A", "B"):
        sources[name] = base / f"{name}.mp4"
        sources[name].write_bytes(f"offline source {name}".encode())
    scenes = [SceneRecord(f"scene_{i:03d}", i, f"Script {i}", f"Cảnh {i}", target_duration=20)
              for i in range(1, 4)]
    clips = [SelectedClipRecord(f"clip_{i}", scene.scene_id, i, "local", source, "Fixture",
        str(sources[source]), start, start + 5, 5, .8, .9, .9, "owned", creator="Fixture creator",
        source_metadata={"media_sha256": fingerprint_file(sources[source]).sha256,
                         "license_basis": "owned"}, **clip_overrides)
        for i, scene, source, start in zip(range(1, 4), scenes, ("A", "B", "A"), (10., 0., 30.))]
    return scenes, clips


def export_package(base: Path, name="library", options=None, clips=None, scenes=None):
    base_scenes, base_clips = make_inputs(base)
    scenes = scenes or base_scenes
    clips = clips or base_clips
    service = FinalExportService(FakeExtractor(), probe=SimpleNamespace(executable=""))
    result = service.export("f017", scenes, clips, base / name,
                            options or ExportOptions(handoff=True))
    assert result.status == "success", result.error
    return result


def load_handoff(package: Path):
    return json.loads((package / HANDOFF_FILENAME).read_text(encoding="utf-8"))


def save_handoff(package: Path, data):
    (package / HANDOFF_FILENAME).write_text(json.dumps(data), encoding="utf-8")
