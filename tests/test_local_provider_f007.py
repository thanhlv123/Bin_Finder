from pathlib import Path

from bin_finder.local_index import LocalMediaIndex
from bin_finder.providers.base import SearchRequest
from bin_finder.providers.local import LocalLibraryProvider


class FakeHasher:
    def hash_media(self, path):
        name = Path(path).name
        return {
            "reference.jpg": "0000000000000000",
            "havana mechanic.mp4": "0000000000000001",
        }.get(name, "")


def test_local_provider_uses_content_hash_source_id(tmp_path: Path):
    root = tmp_path / "library"
    root.mkdir()
    media = root / "havana mechanic.mp4"
    media.write_bytes(b"same-content")
    index = LocalMediaIndex(root, db_path=tmp_path / "index.sqlite3")
    provider = LocalLibraryProvider(str(root), index=index)

    first = provider.search(SearchRequest("scene_001", "havana mechanic"))
    source_id = first.candidates[0].source_id

    renamed = root / "renamed havana mechanic.mp4"
    media.rename(renamed)
    second = provider.search(SearchRequest("scene_001", "havana mechanic"))

    assert second.candidates[0].source_id == source_id
    assert second.candidates[0].preview_url.endswith("renamed havana mechanic.mp4")


def test_local_provider_search_by_image_returns_candidate(tmp_path: Path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "havana mechanic.mp4").write_bytes(b"video")
    reference = tmp_path / "reference.jpg"
    reference.write_bytes(b"image")
    index = LocalMediaIndex(
        root,
        db_path=tmp_path / "index.sqlite3",
        frame_hasher=FakeHasher(),
    )
    provider = LocalLibraryProvider(str(root), index=index)

    result = provider.search_by_image(
        scene_id="scene_001",
        image_path=reference,
        limit=5,
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].provider == "local"
    assert result.candidates[0].score > 0.9
    assert "perceptual frame hash" in result.notice
