"""F017 verifier: fail-closed matrix over a real (fake-extractor) F015 package."""
import json
import shutil
from pathlib import Path

import pytest
from f017_support import export_package, load_handoff, save_handoff

from bin_finder import handoff as core
from bin_finder.final_export import FORMAT as F015_FORMAT
from bin_finder.handoff import HANDOFF_FILENAME, HandoffError, verify_handoff_package


@pytest.fixture
def package(tmp_path):
    return export_package(tmp_path).manifest_path.parent


def code_of(package):
    with pytest.raises(HandoffError) as caught:
        verify_handoff_package(package)
    return caught.value.code


def test_constants_match_f015():
    assert core.MANIFEST_FORMAT == F015_FORMAT


def test_valid_package_passes_and_is_read_only(package):
    before = {p: p.read_bytes() for p in package.rglob("*") if p.is_file()}
    report = verify_handoff_package(package)
    assert (report.clip_count, report.scene_count, report.total_duration_seconds) == (3, 3, 15)
    assert [p.name for p in report.clip_paths] == [f"scene_{i:03d}.mp4" for i in (1, 2, 3)]
    assert before == {p: p.read_bytes() for p in package.rglob("*") if p.is_file()}


def test_package_survives_move_and_rename(tmp_path, package):
    target = tmp_path / "elsewhere" / "renamed"
    target.parent.mkdir()
    package.rename(target)
    assert verify_handoff_package(target).clip_count == 3
    assert str(tmp_path) not in (target / HANDOFF_FILENAME).read_text(encoding="utf-8")


def test_a_b_a_original_coordinates_in_handoff(package):
    scenes = load_handoff(package)["scenes"]
    footage = [s["footage"] for s in scenes]
    assert [f["original_source_start_seconds"] for f in footage] == [10, 0, 30]
    assert [f["source_id"] for f in footage] == ["A", "B", "A"]
    assert [f["relative_path"] for f in footage] == [f"footage/scene_{i:03d}.mp4" for i in (1, 2, 3)]
    assert footage[0]["provenance"]["license_basis"] == "owned"
    assert scenes[0]["vietnamese_text"] == "Cảnh 1"


def test_missing_and_malformed_handoff(tmp_path, package):
    assert code_of(tmp_path / "nope") == "package-missing"
    (package / HANDOFF_FILENAME).write_text("{not json", encoding="utf-8")
    assert code_of(package) == "json-malformed"
    (package / HANDOFF_FILENAME).write_text("[]", encoding="utf-8")
    assert code_of(package) == "json-malformed"
    (package / HANDOFF_FILENAME).write_text('{"a": NaN}', encoding="utf-8")
    assert code_of(package) == "json-nonfinite"
    (package / HANDOFF_FILENAME).unlink()
    assert code_of(package) == "handoff-missing"


def test_duplicate_json_keys(package):
    text = (package / HANDOFF_FILENAME).read_text(encoding="utf-8")
    (package / HANDOFF_FILENAME).write_text(text.replace('"ready": true', '"ready": true, "ready": true'),
                                           encoding="utf-8")
    assert code_of(package) == "json-duplicate-key"


def mutate(package, change):
    data = load_handoff(package)
    change(data)
    save_handoff(package, data)


@pytest.mark.parametrize("name,change,expected", [
    ("format", lambda d: d.update(format="bin_finder_handoff_v2"), "format-unsupported"),
    ("not-ready", lambda d: d.update(ready=False), "not-ready"),
    ("ready-string", lambda d: d.update(ready="true"), "not-ready"),
    ("zero-scenes", lambda d: d.update(scenes=[], scene_count=0, clip_count=0), "no-scenes"),
    ("unknown-key", lambda d: d.update(extra=1), "schema-keys"),
    ("count", lambda d: d.update(clip_count=2), "count-mismatch"),
    ("dup-scene", lambda d: d["scenes"][1].update(scene_id="scene_001"), "scene-duplicate"),
    ("dup-clip", lambda d: d["scenes"][1]["footage"].update(clip_id="clip_1"), "clip-duplicate"),
    ("order", lambda d: d["scenes"][1].update(scene_order=1), "scene-order-invalid"),
    ("order-zero", lambda d: d["scenes"][0].update(scene_order=0), "scene-invalid"),
    ("abs-posix", lambda d: d["scenes"][0]["footage"].update(relative_path="/footage/scene_001.mp4"), "path-absolute-or-unsafe"),
    ("abs-drive", lambda d: d["scenes"][0]["footage"].update(relative_path="C:/footage/scene_001.mp4"), "path-absolute-or-unsafe"),
    ("backslash", lambda d: d["scenes"][0]["footage"].update(relative_path="footage\\scene_001.mp4"), "path-absolute-or-unsafe"),
    ("traversal", lambda d: d["scenes"][0]["footage"].update(relative_path="footage/../scene_001.mp4"), "path-traversal"),
    ("escape", lambda d: d["scenes"][0]["footage"].update(relative_path="../scene_001.mp4"), "path-traversal"),
    ("layout", lambda d: d["scenes"][0]["footage"].update(relative_path="other/scene_001.mp4"), "path-unexpected-layout"),
    ("reserved", lambda d: d["scenes"][0]["footage"].update(relative_path="footage/CON.mp4"), "path-reserved-name"),
    ("path-mismatch", lambda d: d["scenes"][0]["footage"].update(relative_path="footage/scene_009.mp4"), "exported-path-mismatch"),
    ("sha-format", lambda d: d["scenes"][0]["footage"].update(exported_file_sha256="abc"), "sha256-invalid"),
    ("sha-wrong", lambda d: d["scenes"][0]["footage"].update(exported_file_sha256="0" * 64), "manifest-inconsistent"),
    ("bytes-bool", lambda d: d["scenes"][0]["footage"].update(byte_count=True), "byte-count-invalid"),
    ("bytes-wrong", lambda d: d["scenes"][0]["footage"].update(byte_count=1), "byte-count-mismatch"),
    ("duration-zero", lambda d: d["scenes"][0]["footage"].update(duration_seconds=0), "duration-invalid"),
    ("duration-str", lambda d: d["scenes"][0]["footage"].update(duration_seconds="5"), "duration-invalid"),
    ("total", lambda d: d.update(total_duration_seconds=99), "duration-invalid"),
    ("score-high", lambda d: d["scenes"][0]["footage"].update(final_score=1.5), "score-invalid"),
    ("score-neg", lambda d: d["scenes"][0]["footage"].update(vlm_score=-0.1), "score-invalid"),
    ("score-str", lambda d: d["scenes"][0]["footage"].update(semantic_score="0.9"), "score-invalid"),
    ("range-reversed", lambda d: d["scenes"][0]["footage"].update(original_source_end_seconds=5), "range-invalid"),
    ("range-negative", lambda d: d["scenes"][0]["footage"].update(original_source_start_seconds=-1), "range-invalid"),
    ("range-length", lambda d: d["scenes"][0]["footage"].update(original_source_end_seconds=18), "range-invalid"),
    ("scene-id", lambda d: d["scenes"][0].update(scene_id="scene_x"), "scene-identity-mismatch"),
    ("clip-id", lambda d: d["scenes"][0]["footage"].update(clip_id="clip_x"), "clip-identity-mismatch"),
    ("project", lambda d: d.update(project_id="other"), "manifest-inconsistent"),
    ("rights", lambda d: d["scenes"][0]["footage"].update(rights_status="public"), "provenance-mismatch"),
    ("creator", lambda d: d["scenes"][0]["footage"].update(creator="Someone"), "provenance-mismatch"),
    ("provenance-key", lambda d: d["scenes"][0]["footage"].update(provenance={"api_key": "x"}), "provenance-invalid"),
    ("signed-url", lambda d: d["scenes"][0]["footage"].update(source_url="https://e.com/v?token=1"), "provenance-unsafe-url"),
    ("license-url", lambda d: d["scenes"][0]["footage"].update(provenance={"license_url": "https://e.com/l#x"}), "provenance-unsafe-url"),
    ("footage-null", lambda d: d["scenes"][0].update(footage=None), "footage-missing"),
])
def test_handoff_mutations_fail_closed(package, name, change, expected):
    mutate(package, change)
    assert code_of(package) == expected


def test_missing_empty_and_tampered_footage(package):
    victim = package / "footage" / "scene_002.mp4"
    original = victim.read_bytes()
    victim.write_bytes(b"")
    assert code_of(package) == "file-empty"
    victim.write_bytes(original + b"x")
    assert code_of(package) == "byte-count-mismatch"
    victim.write_bytes(b"X" * len(original))
    assert code_of(package) == "sha256-mismatch"
    victim.unlink()
    assert code_of(package) == "file-missing"
    victim.mkdir()
    assert code_of(package) == "file-not-regular"


def test_manifest_missing_malformed_and_inconsistent(package):
    manifest = package / "footage_manifest.json"
    original = manifest.read_text(encoding="utf-8")
    data = json.loads(original)
    for change, expected in ((lambda d: d.update(project_id="other"), "manifest-inconsistent"),
                             (lambda d: d["clips"].pop(), "manifest-inconsistent")):
        change(data)
        manifest.write_text(json.dumps(data), encoding="utf-8")
        assert code_of(package) == "manifest-inconsistent"  # sha no longer matches
        data = json.loads(original)
    # Re-pin the hash so the content comparison itself is exercised.
    for key, value in (("clip_id", "clip_other"), ("exported_path", "footage/scene_009.mp4"),
                       ("rights_status", "public"), ("duration", 4.0)):
        data = json.loads(original)
        data["clips"][0][key] = value
        manifest.write_text(json.dumps(data), encoding="utf-8")
        handoff = load_handoff(package)
        handoff["manifest_sha256"] = core.fingerprint_file(manifest).sha256
        save_handoff(package, handoff)
        assert code_of(package) in {"clip-identity-mismatch", "exported-path-mismatch",
                                    "provenance-mismatch", "manifest-inconsistent"}
    manifest.write_text("{", encoding="utf-8")
    handoff = load_handoff(package)
    handoff["manifest_sha256"] = core.fingerprint_file(manifest).sha256
    save_handoff(package, handoff)
    assert code_of(package) == "manifest-malformed"
    manifest.unlink()
    assert code_of(package) == "manifest-missing"


def test_linked_components_rejected(tmp_path, package):
    link = tmp_path / "link_package"
    try:
        link.symlink_to(package, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks needs Windows privilege or Developer Mode")
    assert code_of(link) == "package-linked"
    real = package / "footage"
    moved = tmp_path / "footage_real"
    real.rename(moved)
    real.symlink_to(moved, target_is_directory=True)
    assert code_of(package) == "path-linked"


def test_junction_rejected(tmp_path, package, monkeypatch):
    footage = package / "footage"
    monkeypatch.setattr(Path, "is_junction", lambda self: self == footage)
    assert code_of(package) == "path-linked"


def test_path_too_long_fails_closed(package, monkeypatch):
    original = core.os.lstat

    def lstat(path, *args, **kwargs):
        if str(path).endswith("scene_001.mp4"):
            error = OSError(36, "File name too long")
            error.winerror = 206
            raise error
        return original(path, *args, **kwargs)
    monkeypatch.setattr(core.os, "lstat", lstat)
    assert code_of(package) == "path-too-long"


def test_verifier_never_modifies_failed_package(package):
    (package / "footage" / "scene_001.mp4").write_bytes(b"tampered")
    before = {p: p.read_bytes() for p in package.rglob("*") if p.is_file()}
    assert code_of(package) == "byte-count-mismatch"
    assert before == {p: p.read_bytes() for p in package.rglob("*") if p.is_file()}
    shutil.rmtree(package / "footage")
    assert code_of(package) == "file-missing"


@pytest.mark.skipif(not hasattr(Path, "is_junction") or __import__("os").name != "nt",
                    reason="real directory junctions are Windows-only")
def test_real_junction_rejected(tmp_path, package):
    import subprocess
    moved = tmp_path / "footage_real"
    (package / "footage").rename(moved)
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(package / "footage"), str(moved)],
                          capture_output=True, check=False)
    if made.returncode:
        pytest.skip("directory junction could not be created")
    assert code_of(package) == "path-linked"
