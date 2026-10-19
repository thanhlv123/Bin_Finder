from bin_finder.demo_data import demo_scenes
from bin_finder.search.query_builder import build_scene_queries


def test_scene_queries_are_deterministic_and_context_first():
    scene = demo_scenes()[0]
    queries = build_scene_queries(scene, max_queries=3)
    assert queries == ["Havana mechanic", "classic Chevrolet", "Cuba street life"]


def test_scene_without_context_falls_back_to_script_words():
    scene = demo_scenes()[2]
    queries = build_scene_queries(scene, max_queries=1)
    assert queries
    assert "Cuban" in queries[0]
    assert "airport" in queries[0]
