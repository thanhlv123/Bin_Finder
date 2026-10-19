from bin_finder.demo_data import demo_scenes
from bin_finder.retrieval.models import RetrievalUnit
from bin_finder.verification.prompt import build_verification_prompt, verification_context
from bin_finder.verification.providers import HeuristicContextVerifier


def test_heuristic_verifier_scores_structured_context():
    scene = demo_scenes()[0]
    units = [
        RetrievalUnit(
            "good",
            "clip.mp4",
            0,
            5,
            transcript_text="Havana mechanic repairs a classic Chevrolet on a Cuba street",
        ),
        RetrievalUnit(
            "bad",
            "clip.mp4",
            5,
            10,
            transcript_text="Shanghai office workers enter a modern subway",
        ),
    ]

    results = HeuristicContextVerifier().verify(scene, units)

    assert results[0].confidence > results[1].confidence
    assert results[0].dimensions.subject_match is not None
    assert results[0].dimensions.location_match is not None


def test_heuristic_verifier_detects_avoid_phrases():
    from dataclasses import replace

    scene = demo_scenes()[0]
    scene = replace(
        scene,
        context=replace(scene.context, avoid=("modern dealership",)),
    )
    unit = RetrievalUnit(
        "conflict",
        "clip.mp4",
        0,
        5,
        metadata_text="modern dealership with classic Chevrolet",
    )

    result = HeuristicContextVerifier().verify(scene, [unit])[0]

    assert result is not None
    assert result.dimensions.context_conflict == 1.0


def test_prompt_contains_context_and_timing():
    scene = demo_scenes()[0]
    unit = RetrievalUnit("u1", "clip.mp4", 1.25, 6.75, "Havana mechanic")
    prompt = build_verification_prompt(scene, unit)
    context = verification_context(scene)

    assert scene.scene_id == context["scene_id"]
    assert "subject_match" in prompt
    assert "1.250-6.750s" in prompt
    assert "Havana mechanic" in prompt
