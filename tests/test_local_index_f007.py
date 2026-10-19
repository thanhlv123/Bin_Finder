from pathlib import Path

from bin_finder.local_index import LocalMediaIndex


class FakeHasher:
    def __init__(self, values=None):
        self.values = values or {}
        self.calls = []

    def hash_media(self, path):
        path = str(path)
        self.calls.append(path)
        return self.values.get(Path(path).name, "")


def test_incremental_sync_skips_unchanged_media(tmp_path: Path):
    root = tmp_path / "library"
    root.mkdir()
    first = root / "havana mechanic.mp4"
    second = root / "airport family.mov"
    first.write_bytes(b"first-video")
    second.write_bytes(b"second-video")

    index = LocalMediaIndex(root, db_path=tmp_path / "index.sqlite3")
    initial = index.sync()
    repeated = index.sync()

    assert initial.scanned_files == 2
    assert initial.hashed_files == 2
    assert initial.indexed_records == 2
    assert repeated.scanned_files == 2
    assert repeated.unchanged_files == 2
    assert repeated.hashed_files == 0


def test_content_hash_survives_rename_and_path_updates(tmp_path: Path):
    root = tmp_path / "library"
    root.mkdir()
    original = root / "old name.mp4"
    original.write_bytes(b"same-content")

    index = LocalMediaIndex(root, db_path=tmp_path / "index.sqlite3")
    index.sync()
    first = index.records()[0]

    renamed = root / "new name.mp4"
    original.rename(renamed)
    stats = index.sync()
    second = index.records()[0]

    assert first.content_sha256 == second.content_sha256
    assert second.path.endswith("new name.mp4")
    assert stats.indexed_records == 1


def test_transcript_change_refreshes_without_rehashing_media(tmp_path: Path):
    root = tmp_path / "library"
    root.mkdir()
    media = root / "cuba.mp4"
    sidecar = root / "cuba.srt"
    media.write_bytes(b"video-bytes")
    sidecar.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHavana mechanic\n",
        encoding="utf-8",
    )

    index = LocalMediaIndex(root, db_path=tmp_path / "index.sqlite3")
    first = index.sync()
    sidecar.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nAirport family goodbye changed\n",
        encoding="utf-8",
    )
    second = index.sync()

    assert first.hashed_files == 1
    assert second.hashed_files == 0
    assert second.refreshed_records == 1
    assert "Airport family goodbye" in index.records()[0].transcript_text


def test_deleted_media_is_removed_from_index(tmp_path: Path):
    root = tmp_path / "library"
    root.mkdir()
    media = root / "clip.mp4"
    media.write_bytes(b"video")

    index = LocalMediaIndex(root, db_path=tmp_path / "index.sqlite3")
    index.sync()
    media.unlink()
    stats = index.sync()

    assert stats.removed_records == 1
    assert stats.indexed_records == 0


def test_text_search_uses_filename_and_transcript(tmp_path: Path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "generic.mp4").write_bytes(b"a")
    (root / "generic.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nHavana mechanic classic Chevrolet\n",
        encoding="utf-8",
    )
    (root / "airport family.mp4").write_bytes(b"b")

    index = LocalMediaIndex(root, db_path=tmp_path / "index.sqlite3")
    index.sync()
    matches = index.search_text("Havana mechanic", limit=5)

    assert matches
    assert matches[0][1].title == "generic"
    assert matches[0][0] == 1.0


def test_image_search_lazily_hashes_and_ranks(tmp_path: Path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "close.mp4").write_bytes(b"a")
    (root / "far.mp4").write_bytes(b"b")
    reference = tmp_path / "reference.jpg"
    reference.write_bytes(b"image")

    hasher = FakeHasher(
        {
            "reference.jpg": "0000000000000000",
            "close.mp4": "0000000000000001",
            "far.mp4": "ffffffffffffffff",
        }
    )
    index = LocalMediaIndex(
        root,
        db_path=tmp_path / "index.sqlite3",
        frame_hasher=hasher,
    )
    index.sync()

    matches = index.search_image(reference, limit=2)

    assert [item.title for _, item in matches] == ["close", "far"]
    assert matches[0][0] > matches[1][0]

    call_count = len(hasher.calls)
    again = index.search_image(reference, limit=2)
    assert [item.title for _, item in again] == ["close", "far"]
    assert len(hasher.calls) == call_count + 1
