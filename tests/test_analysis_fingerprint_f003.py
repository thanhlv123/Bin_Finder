from pathlib import Path

from bin_finder.analysis.fingerprint import fingerprint_file


def test_fingerprint_is_content_stable_across_renames(tmp_path: Path):
    original = tmp_path / "first.mp4"
    original.write_bytes(b"same media bytes")
    first = fingerprint_file(original)

    renamed = tmp_path / "renamed.mp4"
    original.rename(renamed)
    second = fingerprint_file(renamed)

    assert first.sha256 == second.sha256
    assert first.size_bytes == second.size_bytes
    assert len(first.sha256) == 64


def test_fingerprint_changes_when_content_changes(tmp_path: Path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"A")
    first = fingerprint_file(path)
    path.write_bytes(b"B")
    second = fingerprint_file(path)
    assert first.sha256 != second.sha256
