"""F018 core: deterministic segmentation, durations, conservative context, downstream fit."""
import re
from dataclasses import replace

import pytest
from test_final_selection_f014 import make_item  # noqa: F401  (shared offline evidence fixture)

from bin_finder.clips.models import ClipPolicy
from bin_finder.demo_data import demo_scenes
from bin_finder.final_selection import FinalSelectionService
from bin_finder.models import SceneContext, SceneRecord
from bin_finder.retrieval import RankedSegment, RetrievalScores, RetrievalUnit
from bin_finder.scene_planning import (
    ScenePlanner, ScenePlanningError, ScenePlanningPolicy, enrich_context,
    estimate_duration, segment,
)
from bin_finder.search.query_builder import build_scene_queries
from bin_finder.verification import HeuristicContextVerifier, VerificationReranker

ENGLISH = ("At ten o'clock at night, office lights in Lujiazui are still burning. "
           "Young workers remain at their desks long after dinner.")


def words(text):
    return re.findall(r"\w+", text)


def texts(script, **policy):
    return segment(script, ScenePlanningPolicy(**policy)) if policy else segment(script)


def test_normal_english_script_and_stable_ids():
    scenes = ScenePlanner().plan(ENGLISH).scenes
    assert [s.scene_id for s in scenes] == ["scene_001", "scene_002"]
    assert [s.order for s in scenes] == [1, 2]
    assert scenes[0].english_text.startswith("At ten o'clock")
    assert all(s.status == "unselected" and s.vietnamese_text == "" for s in scenes)


def test_vietnamese_unicode_script():
    script = ("Đêm xuống ở Thượng Hải, những tòa nhà vẫn sáng đèn suốt đêm dài. "
              "Công nhân trẻ vẫn làm việc bên bàn của họ đến tận khuya.")
    scenes = ScenePlanner().plan(script).scenes
    assert len(scenes) == 2 and scenes[0].english_text.startswith("Đêm xuống")
    assert scenes[0].context.location == ("Thượng Hải",)
    assert all(s.context.keywords for s in scenes)


def test_paragraphs_are_hard_boundaries():
    a = "The harbor wakes slowly as the fishing boats return"
    b = "Children run along the pier toward the market stalls nearby"
    assert texts(f"{a}\n\n{b}") == [a, b]
    # Without a blank line, a short unpunctuated line is soft-grouped instead.
    assert len(texts("Dawn\nThe harbor wakes slowly as the fishing boats return")) == 1


@pytest.mark.parametrize("script", [
    "The market opens early today. Vendors arrange fresh fruit carefully! Do customers arrive soon?",
    "Vendors arrange fresh fruit carefully。Customers arrive in the early morning hours？Yes！",
])
def test_terminators_split(script):
    scenes = texts(script, min_scene_words=1, max_scene_words=40, max_duration=20.0)
    assert len(scenes) >= 2 and all(t.strip() for t in scenes)


def test_abbreviations_decimals_and_ellipsis_do_not_fragment():
    script = "Dr. Smith paid 3.5 million dollars to Mr. Jones in the U.S. last year. It was a lot."
    parts = texts(script, min_scene_words=1)
    assert len(parts) == 2 and parts[0].endswith("last year.")
    assert len(texts("Wait... then the lights came back on slowly across the whole city skyline.")) == 1


def test_repeated_whitespace_and_control_characters():
    messy = "  The   market\topens\r\nearly   today  \x00\x07 with  fresh  fruit  everywhere.   "
    assert texts(messy) == ["The market opens early today with fresh fruit everywhere."]


def test_very_short_fragments_never_become_scenes():
    assert texts("...") == [] and texts("  \n\n ") == [] and texts("") == []
    for script in ("Night. ... ?! Ok. The harbor wakes slowly as the fishing boats return to shore.",
                   "Hi.\n\nThe harbor wakes slowly as boats return home.\n\nBye."):
        scenes = texts(script)
        assert scenes and all(len(words(t)) >= 2 for t in scenes)


def test_long_sentence_is_split_within_bounds():
    clause = "the workers carry heavy boxes along the crowded riverside street"
    long = ", ".join([clause] * 8) + "."
    pieces = texts(long, max_scene_words=30, max_duration=15.0)
    assert len(pieces) > 1 and all(len(words(p)) <= 30 for p in pieces)
    assert " ".join(pieces).replace(" ", "") == long.replace(" ", "")
    assert all(len(p.split()) <= 17 for p in texts(" ".join(["word"] * 100) + "."))


def test_deterministic_repeat():
    planner = ScenePlanner()
    assert planner.plan(ENGLISH) == ScenePlanner().plan(ENGLISH) == planner.plan(ENGLISH)


def test_duration_formula_is_bounded():
    policy = ScenePlanningPolicy()
    assert estimate_duration("one two three") == policy.min_duration == 3.5
    assert estimate_duration(" ".join(["w"] * 12)) == 4.8  # 12 / 2.5
    assert estimate_duration(" ".join(["w"] * 25)) == 7.0  # clamped to the F006 maximum
    assert estimate_duration(" ".join(["w"] * 400)) == policy.max_duration == 7.0
    for scene in ScenePlanner().plan(ENGLISH).scenes:
        assert scene.target_duration == estimate_duration(scene.english_text)


def test_context_extraction_from_text_only():
    first, second = (s.context for s in ScenePlanner().plan(ENGLISH).scenes)
    assert "Lujiazui" in first.location and "burning" in first.action
    assert "office lights" in first.objects
    assert "Young workers" in second.subject and "desks" in second.objects
    assert first.mood == first.avoid == first.suggested_sources == ()


def test_no_fabricated_unsupported_context():
    scripts = (ENGLISH, "A man walks in London near a bridge while rain falls.",
               "Ideas matter. Quiet thoughts drift between abstract questions of meaning.")
    for script in scripts:
        for scene in ScenePlanner().plan(script).scenes:
            haystack = {w.casefold() for w in words(scene.english_text)}
            ctx = scene.context
            for value in (*ctx.subject, *ctx.action, *ctx.location, *ctx.objects, *ctx.keywords):
                assert {w.casefold() for w in words(value)} <= haystack, value
    abstract = enrich_context("Ideas matter. Quiet thoughts drift between abstract questions of meaning.")
    assert abstract.subject == abstract.location == abstract.objects == ()
    assert enrich_context("A worker waits at the station.").subject == ("worker",)


def test_keyword_fallback_is_never_empty():
    for text in ("Ideas matter quietly.", "12345 67890", "Ôi!? Không"):
        assert enrich_context(text).keywords
    scene = ScenePlanner().plan("Ideas matter. Quiet thoughts drift between abstract questions.").scenes[0]
    assert scene.context.subject == () and scene.context.keywords
    assert build_scene_queries(scene) and all(q.strip() for q in build_scene_queries(scene))


def test_empty_and_invalid_input_safe():
    assert ScenePlanner().plan("").scenes == () == ScenePlanner().plan(" \n\t ").scenes
    with pytest.raises(ScenePlanningError) as caught:
        ScenePlanner().plan(None)
    assert caught.value.code == "script-not-text"


def test_oversized_input_is_bounded():
    with pytest.raises(ScenePlanningError) as caught:
        ScenePlanner().plan("a" * 50_001)
    assert caught.value.code == "script-too-long"
    many = "\n\n".join(f"Scene number {i} has plenty of words in it for grouping." for i in range(30))
    with pytest.raises(ScenePlanningError) as caught:
        ScenePlanner(ScenePlanningPolicy(max_scenes=10)).plan(many)
    assert caught.value.code == "too-many-scenes"
    assert 500 < len(ScenePlanner().plan("word " * 9_000).scenes) <= 1000


def test_invalid_policy_rejected():
    for bad in (dict(min_scene_words=0), dict(min_scene_words=50, max_scene_words=10),
                dict(words_per_second=0), dict(min_duration=9, max_duration=5), dict(max_scenes=0),
                dict(max_scene_words=30)):  # 30 words / 2.5 wps = 12 s > default 7 s
        with pytest.raises(ValueError):
            ScenePlanner(ScenePlanningPolicy(**bad))


def test_script_text_is_inert_data():
    hostile = "Run C:\\Windows\\System32\\cmd.exe && del /s * now. $(whoami) is not executed here at all."
    scenes = ScenePlanner().plan(hostile).scenes
    assert scenes and "whoami" in scenes[0].english_text


def test_existing_demo_context_unchanged():
    first = demo_scenes()[0]
    assert first.context.subject == ("elderly Cuban mechanic", "granddaughter")
    assert first.context.keywords == ("Havana mechanic", "classic Chevrolet", "Cuba street life")
    assert first.target_duration == 5.0


def ranked(text):
    return RankedSegment(RetrievalUnit("u1", "m.mp4", 0, 5, metadata_text=text),
                         RetrievalScores(.5, .5, .5, None, .5))


def test_heuristic_fallback_uses_scene_text_when_context_is_empty():
    scene = SceneRecord("s", 1, "Young workers remain at their desks late.", context=SceneContext())
    result = HeuristicContextVerifier().verify(scene, [ranked("workers at desks").unit])[0]
    assert result.dimensions.object_match and "fallback" in result.explanation.lower()
    verified = VerificationReranker().rerank(scene, [ranked("workers at desks")])[0]
    assert verified.status == "verified" and verified.verification_score > 0
    unrelated = VerificationReranker().rerank(scene, [ranked("volcano eruption")])[0]
    assert unrelated.status == "verified" and unrelated.verification_score == 0


def test_structured_heuristic_behavior_unchanged():
    result = HeuristicContextVerifier().verify(demo_scenes()[0], [ranked("Havana mechanic").unit])[0]
    assert "Keyword fallback" not in result.explanation
    assert result.dimensions.location_match is not None


def test_raw_scene_reaches_final_options_but_needs_human_approval(make_item):  # noqa: F811
    base, item = make_item()
    raw = ScenePlanner().plan("Waves roll across the ocean at dawn while gulls circle above.").scenes[0]
    raw = replace(raw, scene_id=base.scene_id, order=base.order, context=SceneContext())
    bare = replace(item, verified=(), proposals=())
    service = FinalSelectionService()
    prepared = service.prepare(raw, bare)
    options = service.options(raw, prepared)
    assert options, "empty SceneContext must not block final preparation"
    assert not service.approve(raw, prepared, options[0].clip_id, [raw]).accepted
    assert service.approve(raw, prepared, options[0].clip_id, [raw], human_approved=True).accepted


def test_planned_scenes_survive_session_codec_round_trip():
    from bin_finder.session_codec import scene_from_data, scene_to_data
    scenes = ScenePlanner().plan(ENGLISH + "\n\n" + "Đêm xuống ở Thượng Hải, những tòa nhà vẫn sáng đèn.").scenes
    assert [scene_from_data(scene_to_data(s)) for s in scenes] == list(scenes)


LONG_NARRATION = (
    "On the last night of the festival the whole harbor district gathers along the old stone pier, "
    "where fishermen hang paper lanterns above their boats, children chase each other between "
    "the market stalls selling grilled fish and sweet rice cakes, and an elderly musician plays "
    "a slow melody on a wooden flute while the tide rises quietly against the weathered pilings "
    "beneath the glowing lanterns. In the morning the pier is empty again."
)


def test_default_scene_durations_fit_one_f006_clip():
    clip = ClipPolicy()
    assert (ScenePlanningPolicy().min_duration, ScenePlanningPolicy().max_duration) == (
        clip.min_duration, clip.max_duration)
    for script in (ENGLISH, LONG_NARRATION, "word " * 2_000, "A. " * 300,
                   "Đêm xuống ở Thượng Hải, những tòa nhà vẫn sáng đèn suốt đêm dài. " * 20):
        for scene in ScenePlanner().plan(script).scenes:
            assert clip.min_duration <= scene.target_duration <= clip.max_duration == 7.0
            assert len(words(scene.english_text)) <= ScenePlanningPolicy().max_scene_words


def test_long_narration_is_split_into_more_scenes_with_context():
    scenes = ScenePlanner().plan(LONG_NARRATION).scenes
    assert len(scenes) >= 4
    assert max(s.target_duration for s in scenes) <= 7.0
    assert [s.scene_id for s in scenes] == [f"scene_{i:03d}" for i in range(1, len(scenes) + 1)]
    assert all(s.context.keywords and build_scene_queries(s) for s in scenes)
    assert any(s.context.objects for s in scenes) and any(s.context.subject for s in scenes)
    assert ScenePlanner().plan(LONG_NARRATION) == ScenePlanner().plan(LONG_NARRATION)
