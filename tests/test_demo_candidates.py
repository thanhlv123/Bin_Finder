from bin_finder.demo_data import demo_candidates


def test_demo_candidates_change_with_scene():
    scene_1 = demo_candidates("scene_001")
    scene_3 = demo_candidates("scene_003")
    assert scene_1[0].scene_id == "scene_001"
    assert scene_3[0].scene_id == "scene_003"
    assert scene_1[0].candidate_id != scene_3[0].candidate_id
    assert scene_1[0].title != scene_3[0].title


def test_each_demo_scene_has_three_or_more_results():
    for scene_id in ("scene_001", "scene_002", "scene_003", "scene_004", "scene_005"):
        assert len(demo_candidates(scene_id)) >= 3
        assert all(candidate.scene_id == scene_id for candidate in demo_candidates(scene_id))
