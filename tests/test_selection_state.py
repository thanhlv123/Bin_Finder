from bin_finder.demo_data import demo_candidates, demo_scenes
from bin_finder.selection_state import SceneSelectionIndex


def _candidate(scene_id: str, index: int = 0):
    return demo_candidates(scene_id)[index]


def test_sparse_scene_selection_is_sorted_by_script_order():
    scenes = demo_scenes()
    state = SceneSelectionIndex.from_scenes(scenes)
    state.add_or_replace(_candidate("scene_003", 0))
    state.add_or_replace(_candidate("scene_001", 0))
    assert state.ordered_scene_ids() == ["scene_001", "scene_003"]


def test_later_scene_inserts_between_existing_sparse_selection():
    scenes = demo_scenes()
    state = SceneSelectionIndex.from_scenes(scenes)
    state.add_or_replace(_candidate("scene_001", 0))
    state.add_or_replace(_candidate("scene_003", 0))
    state.add_or_replace(_candidate("scene_002", 0))
    assert state.ordered_scene_ids() == ["scene_001", "scene_002", "scene_003"]


def test_reselecting_same_scene_replaces_without_growing_count():
    scenes = demo_scenes()
    state = SceneSelectionIndex.from_scenes(scenes)
    first = _candidate("scene_001", 0)
    replacement = _candidate("scene_001", 2)
    state.add_or_replace(first)
    state.add_or_replace(replacement)
    assert len(state) == 1
    assert state.ordered_candidates()[0].candidate_id == replacement.candidate_id
