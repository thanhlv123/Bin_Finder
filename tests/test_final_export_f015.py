import csv
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import bin_finder.final_export as core
from bin_finder.acceptance import evaluate_project
from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.clips.extractor import FfmpegClipExtractor
from bin_finder.clips.models import ExtractionResult
from bin_finder.final_export import ExportOptions, FinalExportService
from bin_finder.final_selection import build_final_project
from bin_finder.models import SceneRecord, SelectedClipRecord


class FakeExtractor(FfmpegClipExtractor):
    def __init__(self):
        super().__init__(executable="offline-ffmpeg")
        self.calls = []
        self.after_extract = None

    def extract(self, proposal, output_path, *, overwrite=False):
        self.calls.append((proposal, output_path, overwrite))
        assert proposal.accepted and overwrite is False
        assert not output_path.exists()
        output_path.write_bytes(f"clip:{proposal.unit_id}".encode())
        if self.after_extract:
            self.after_extract(proposal, output_path)
        return ExtractionResult(str(output_path), output_path.stat().st_size, proposal.duration)


@pytest.fixture
def fixture_export(tmp_path):
    sources = {}
    for name in ("A", "B"):
        source = tmp_path / f"{name}.mp4"
        source.write_bytes(f"offline source {name}".encode())
        sources[name] = source
    scenes = [SceneRecord(f"scene_{i:03d}", i, "Fixture", target_duration=20) for i in range(1, 4)]
    clips = [SelectedClipRecord(f"clip_{i}", scene.scene_id, i, "local", source, "Fixture",
        str(sources[source]), start, start + 5, 5, .8, .9, .9, "owned", creator="Fixture creator",
        source_metadata={"media_sha256": fingerprint_file(sources[source]).sha256,
                         "license_basis": "owned"})
        for i, scene, source, start in zip(range(1, 4), scenes, ("A", "B", "A"), (10., 0., 30.))]
    extractor = FakeExtractor()
    service = FinalExportService(extractor, probe=SimpleNamespace(executable=""))
    return SimpleNamespace(scenes=scenes, clips=clips, destination=tmp_path / "library",
        service=service, extractor=extractor, sources=sources)


def export(f, **kwargs):
    return f.service.export("test", f.scenes, f.clips, f.destination, **kwargs)


def assert_no_publication(f):
    assert not f.destination.exists()
    assert not list(f.destination.parent.glob(".bin-finder-export-partial-*"))


def test_incomplete_is_structured_and_creates_nothing(fixture_export):
    f = fixture_export
    f.clips.pop()
    result = export(f)
    assert result.status == "not_ready" and not result.readiness.ready
    assert result.readiness.unresolved_scene_ids == ("scene_003",)
    assert not f.extractor.calls
    assert_no_publication(f)


def test_aba_uses_original_report_once_and_materializes_adapter(fixture_export, monkeypatch):
    f = fixture_export
    original = build_final_project("test", f.scenes, f.clips, f.destination)
    assert evaluate_project(original).ready
    reports = []
    def evaluate(project):
        assert [c.start for c in project.selected_clips] == [10, 0, 30]
        report = evaluate_project(project)
        reports.append(report)
        return report
    monkeypatch.setattr(core, "evaluate_project", evaluate)
    result = export(f, options=ExportOptions(integration_adapter=True))
    assert result.status == "success", result.error
    assert len(reports) == 1 and result.readiness is reports[0]
    assert result.exported_count == 3 and result.total_duration == 15
    assert [p.name for p in result.clip_paths] == [f"scene_{i:03d}.mp4" for i in range(1, 4)]
    assert len(f.extractor.calls) == 3
    assert all(not overwrite for _, _, overwrite in f.extractor.calls)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == "bin_finder_final_export_v1"
    assert manifest["readiness"]["ready"] and manifest["exported_count"] == 3
    assert manifest["exported_at"].endswith("+00:00")
    assert [r["original_source_start_seconds"] for r in manifest["clips"]] == [10, 0, 30]
    assert [r["original_source_end_seconds"] for r in manifest["clips"]] == [15, 5, 35]
    adapter = json.loads(result.adapter_paths[0].read_text(encoding="utf-8"))
    assert adapter["format"] == "ai_video_editor_bin_finder_adapter_v1"
    assert adapter["ready"] and adapter["project_id"] == "test"
    for scene, original_clip, path, row in zip(adapter["scenes"], f.clips, result.clip_paths, manifest["clips"]):
        footage = scene["footage"]
        assert footage["source_id"] == original_clip.source_id
        assert footage["clip_id"] == original_clip.clip_id
        assert Path(footage["path"]) == path and path.is_file()
        assert footage["source_start_seconds"] == 0
        assert footage["source_end_seconds"] == footage["duration_seconds"] == 5
        assert row["scene_id"] == original_clip.scene_id and row["clip_id"] == original_clip.clip_id
        assert row["exported_path"] == f"footage/{path.name}"
        assert row["exported_file_sha256"] == fingerprint_file(path).sha256
        assert row["original_source_media_sha256"] == original_clip.source_metadata["media_sha256"]
        assert footage["source_metadata"]["f015_original_source_start_seconds"] == original_clip.start
    acceptance = json.loads(result.adapter_paths[1].read_text(encoding="utf-8"))
    assert acceptance == json.loads(json.dumps(reports[0].to_dict()))
    assert acceptance["ready"] and not acceptance["overlap_issues"]
    assert not list(f.destination.parent.glob(".bin-finder-export-partial-*"))


def test_default_no_adapter_and_deterministic_csv(fixture_export):
    f = fixture_export
    f.scenes.reverse()
    f.clips.reverse()
    result = export(f)
    assert result.status == "success" and result.adapter_paths == ()
    assert not list(f.destination.glob("_ai*"))
    with result.csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [r["scene_order"] for r in rows] == ["1", "2", "3"]
    assert [r["clip_id"] for r in rows] == ["clip_1", "clip_2", "clip_3"]
    assert [r["filename"] for r in rows] == [p.name for p in result.clip_paths]


def test_final_evidence_and_rendition_provenance_preserved(fixture_export):
    f = fixture_export
    metadata = {**f.clips[0].source_metadata, "proposal_unit_id": "verified-unit",
        "verification_provider": "fixture-verifier", "duplicate_group": "safe-group",
        "selected_rendition": {"identifier": "a" * 64, "width": 1920, "height": 1080}}
    f.clips[0] = replace(f.clips[0], source_metadata=metadata)
    result = export(f, options=ExportOptions(integration_adapter=True))
    assert result.status == "success"
    manifest_metadata = json.loads(result.manifest_path.read_text(encoding="utf-8"))["clips"][0]["source_metadata"]
    adapter_metadata = json.loads(result.adapter_paths[0].read_text(encoding="utf-8"))["scenes"][0]["footage"]["source_metadata"]
    for key in ("proposal_unit_id", "verification_provider", "duplicate_group", "selected_rendition", "license_basis"):
        assert manifest_metadata[key] == adapter_metadata[key] == metadata[key]


def test_each_source_revalidated_before_its_extraction(fixture_export):
    f = fixture_export
    f.extractor.after_extract = lambda *_: f.sources["B"].write_bytes(b"modified after first scene")
    result = export(f)
    assert result.status == "failed" and result.error == "source-sha256-changed"
    assert len(f.extractor.calls) == 1
    assert_no_publication(f)


@pytest.mark.parametrize("kind", ["missing", "directory", "changed", "negative", "nan", "infinite", "reversed", "duration", "short", "long"])
def test_source_integrity_fails_closed(fixture_export, kind):
    f = fixture_export
    clip = f.clips[0]
    if kind == "missing": f.sources["A"].unlink()
    elif kind == "directory": f.clips[0] = replace(clip, local_file=str(f.destination.parent))
    elif kind == "changed": f.sources["A"].write_bytes(b"changed since approval")
    else:
        changes = {"negative": {"start": -1}, "nan": {"start": float("nan")},
            "infinite": {"end": float("inf")}, "reversed": {"end": 9},
            "duration": {"duration": 4}, "short": {"end": 12, "duration": 2},
            "long": {"end": 18, "duration": 8}}[kind]
        f.clips[0] = replace(clip, **changes)
    result = export(f)
    # Infinite source end also violates original F010 same-source overlap first.
    assert result.status == ("not_ready" if kind == "infinite" else "failed")
    assert not f.extractor.calls
    assert_no_publication(f)


def test_symlink_source_rejected_when_supported(fixture_export):
    f = fixture_export
    link = f.destination.parent / "alias.mp4"
    try:
        link.symlink_to(f.sources["A"])
    except OSError:
        pytest.skip("Creating symlinks needs Windows privilege or Developer Mode")
    f.clips[0] = replace(f.clips[0], local_file=str(link))
    assert export(f).error == "source-not-regular"
    assert_no_publication(f)


@pytest.mark.parametrize("failure", ["extractor", "empty", "missing", "duration", "path", "bytes", "probe", "source_mutation", "metadata", "adapter"])
def test_failures_never_publish_partial_library(fixture_export, monkeypatch, failure):
    f = fixture_export
    if failure == "extractor":
        def fail(proposal, path):
            if len(f.extractor.calls) == 2:
                raise RuntimeError("deterministic failure")
        f.extractor.after_extract = fail
    elif failure in ("empty", "missing"):
        def damage(proposal, path):
            path.write_bytes(b"") if failure == "empty" else path.unlink()
        f.extractor.after_extract = damage
    elif failure in ("duration", "path", "bytes"):
        extract = f.extractor.extract
        def bad_result(*args, **kwargs):
            result = extract(*args, **kwargs)
            return replace(result, **{"duration": {"duration": 4}, "path": {"output_path": "wrong"},
                                      "bytes": {"bytes_written": 0}}[failure])
        monkeypatch.setattr(f.extractor, "extract", bad_result)
    elif failure == "probe":
        f.service.probe = SimpleNamespace(executable="probe", probe=lambda path: SimpleNamespace(duration=3, width=160))
    elif failure == "source_mutation":
        f.extractor.after_extract = lambda *_: f.sources["A"].write_bytes(b"changed during extraction")
    elif failure == "metadata":
        write = Path.write_text
        def fail_write(path, *args, **kwargs):
            if path.name == "footage_manifest.json": raise OSError("disk error")
            return write(path, *args, **kwargs)
        monkeypatch.setattr(Path, "write_text", fail_write)
    elif failure == "adapter":
        def fail_adapter(*args): raise OSError("adapter write error")
        monkeypatch.setattr(core, "write_integration_package", fail_adapter)
    result = export(f, options=ExportOptions(integration_adapter=failure == "adapter"))
    assert result.status == "failed"
    assert_no_publication(f)


@pytest.mark.parametrize("when", ["before", "during", "after_last"])
def test_cooperative_cancellation_never_publishes(fixture_export, when):
    f = fixture_export
    cancel = [when == "before"]
    def after(*_):
        if when == "during" or len(f.extractor.calls) == 3:
            cancel[0] = True
    f.extractor.after_extract = after
    result = export(f, cancelled=lambda: cancel[0])
    assert result.status == "cancelled"
    assert len(f.extractor.calls) == {"before": 0, "during": 1, "after_last": 3}[when]
    assert_no_publication(f)


def test_safe_provenance_no_secrets_signed_queries_or_raw_metadata(fixture_export, monkeypatch):
    f = fixture_export
    secret = "f015-test-only-secret-value"
    monkeypatch.setenv("BIN_FINDER_PEXELS_API_KEY", secret)
    f.clips = [replace(c, title=secret, creator=secret, source_url="https://example.com/video?token=" + secret,
        source_metadata={**c.source_metadata, "Authorization": "Bearer " + secret,
            "raw_response": {"secret": secret}, "api_key": secret,
            "license_url": "https://example.com/license?signed=" + secret,
            "license_basis": "owned " + secret}) for c in f.clips]
    result = export(f, options=ExportOptions(integration_adapter=True))
    assert result.status == "success"
    serialized = "\n".join(p.read_text(encoding="utf-8") for p in f.destination.iterdir() if p.is_file())
    for forbidden in (secret, "Authorization", "raw_response", "api_key", "?token=", "?signed="):
        assert forbidden not in serialized
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["clips"][0]["source_metadata"]["license_url"] == "https://example.com/license"


def test_existing_completed_export_not_overwritten(fixture_export):
    f = fixture_export
    first = export(f)
    assert first.status == "success"
    before = {p.relative_to(f.destination): p.read_bytes() for p in f.destination.rglob("*") if p.is_file()}
    calls = len(f.extractor.calls)
    second = export(f)
    assert second.status == "failed" and second.error == "destination-exists"
    assert len(f.extractor.calls) == calls
    assert before == {p.relative_to(f.destination): p.read_bytes() for p in f.destination.rglob("*") if p.is_file()}


def test_source_repository_destination_rejected(fixture_export):
    f = fixture_export
    f.destination = Path(core.__file__).resolve().parents[2] / "never-created-f015"
    assert export(f).error == "output-inside-source-tree"
    assert not f.destination.exists() and not f.extractor.calls


def test_empty_selected_folder_and_optional_outputs(fixture_export):
    f = fixture_export
    f.destination.mkdir()
    result = export(f, options=ExportOptions(csv_index=False, include_metadata=False))
    assert result.status == "success" and result.csv_path is None
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert "source_metadata" not in manifest["clips"][0]
    assert "final_score" in manifest["clips"][0]
    assert not (f.destination / "footage_index.csv").exists()


def test_f006_default_extractor_reused(fixture_export, monkeypatch):
    f = fixture_export
    calls = []
    def run(command, **kwargs):
        assert kwargs.get("shell", False) is False
        assert "-n" in command and "-y" not in command
        calls.append(command)
        Path(command[-1]).write_bytes(b"fixture output")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("bin_finder.clips.extractor.subprocess.run", run)
    monkeypatch.setenv("BIN_FINDER_FFMPEG", "fixture-ffmpeg")
    f.service = FinalExportService(probe=SimpleNamespace(executable=""))
    assert isinstance(f.service.extractor, FfmpegClipExtractor)
    assert export(f).status == "success" and len(calls) == 3
    assert [c[c.index("-ss") + 1] for c in calls] == ["10.000", "0.000", "30.000"]


@pytest.mark.parametrize("scene_id,expected", [("../unsafe", "scene_001.mp4"), ("CON", "scene_001.mp4"),
    ("com1", "scene_001.mp4"), ("custom_scene", "custom_scene.mp4"), ("remote:title", "scene_001.mp4")])
def test_scene_filenames_safe(scene_id, expected):
    assert core._filename(scene_id, 1, True) == expected
    assert core._filename(scene_id, 1, False) == "scene_001.mp4"


@pytest.mark.parametrize("mutation", ["project", "scene", "count", "clip", "source", "duration", "missing", "empty"])
def test_materialized_consistency_fails_closed(fixture_export, mutation):
    f = fixture_export
    original = build_final_project("test", f.scenes, f.clips, f.destination)
    report = evaluate_project(original)
    stage = f.destination.parent / "stage"
    (stage / "footage").mkdir(parents=True)
    materialized = build_final_project("test", f.scenes,
        [replace(c, local_file=str(f.destination / "footage" / f"{c.scene_id}.mp4"), start=0, end=5) for c in f.clips],
        f.destination)
    for c in materialized.selected_clips:
        (stage / "footage" / Path(c.local_file).name).write_bytes(b"clip")
    core._validate_materialized(original, report, materialized, stage)
    if mutation == "project": materialized.project_id = "different"
    elif mutation == "scene": materialized.scenes = list(reversed(f.scenes))
    elif mutation == "count": materialized.selected_clips.pop()
    elif mutation in ("clip", "source", "duration"):
        materialized.selected_clips[0] = replace(materialized.selected_clips[0], **{
            "clip": {"clip_id": "wrong"}, "source": {"source_id": "wrong"},
            "duration": {"duration": 4}}[mutation])
    elif mutation == "missing": (stage / "footage" / "scene_001.mp4").unlink()
    elif mutation == "empty": (stage / "footage" / "scene_001.mp4").write_bytes(b"")
    with pytest.raises(ValueError):
        core._validate_materialized(original, report, materialized, stage)


def test_smoke_requires_explicit_approval(monkeypatch, capsys):
    import bin_finder.final_export_smoke as smoke
    monkeypatch.setattr(smoke, "run_smoke", lambda: pytest.fail("unapproved smoke executed"))
    assert smoke.main([]) == 0
    assert capsys.readouterr().out.strip() == "SKIPPED_NOT_APPROVED"


def test_smoke_without_ffmpeg_is_not_a_pass(monkeypatch, capsys):
    import bin_finder.final_export_smoke as smoke
    monkeypatch.setattr(smoke, "FfmpegClipExtractor", lambda **_: SimpleNamespace(executable=""))
    assert smoke.main(["--approve-test-export"]) == 2
    assert capsys.readouterr().out.strip() == "SKIPPED_NO_FFMPEG"
