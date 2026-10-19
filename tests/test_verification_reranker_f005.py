from bin_finder.demo_data import demo_scenes
from bin_finder.retrieval.models import RankedSegment, RetrievalScores, RetrievalUnit
from bin_finder.verification.models import VerificationDimensions, VerificationResult
from bin_finder.verification.reranker import RerankWeights, VerificationReranker


def ranked(unit_id, base_score, start):
    return RankedSegment(
        unit=RetrievalUnit(unit_id, "clip.mp4", start, start + 5, unit_id),
        scores=RetrievalScores(
            bm25=base_score,
            exact=0.0,
            text_similarity=base_score,
            visual_similarity=None,
            final=base_score,
        ),
    )


class FixedVerifier:
    name = "fake-vlm"

    def __init__(self, results):
        self.results = results
        self.calls = []

    def verify(self, scene, units):
        self.calls.append([unit.unit_id for unit in units])
        return list(self.results)


class BrokenVerifier:
    name = "broken"

    def verify(self, scene, units):
        raise RuntimeError("boom")


def result(unit_id, match, conflict=0.0, confidence=1.0):
    return VerificationResult(
        unit_id=unit_id,
        provider="fake-vlm",
        dimensions=VerificationDimensions(
            subject_match=match,
            action_match=match,
            location_match=match,
            object_match=match,
            time_match=match,
            visual_quality=match,
            context_conflict=conflict,
        ),
        confidence=confidence,
    )


def test_verifier_can_rerank_top_candidates():
    items = [ranked("a", 0.9, 0), ranked("b", 0.8, 5)]
    verifier = FixedVerifier([result("a", 0.1), result("b", 1.0)])
    reranker = VerificationReranker(
        verifier,
        rerank_weights=RerankWeights(retrieval=0.2, verification=0.8),
    )

    output = reranker.rerank(demo_scenes()[0], items)

    assert output[0].segment.unit.unit_id == "b"
    assert output[0].status == "verified"
    assert output[0].final_score > output[1].final_score


def test_context_conflict_can_demote_otherwise_strong_match():
    items = [ranked("a", 0.9, 0), ranked("b", 0.85, 5)]
    verifier = FixedVerifier([
        result("a", 1.0, conflict=1.0),
        result("b", 0.85, conflict=0.0),
    ])
    output = VerificationReranker(
        verifier,
        rerank_weights=RerankWeights(retrieval=0.2, verification=0.8),
    ).rerank(demo_scenes()[0], items)

    assert output[0].segment.unit.unit_id == "b"


def test_only_top_n_is_sent_to_provider_and_tail_stays_after_block():
    items = [
        ranked("a", 0.9, 0),
        ranked("b", 0.8, 5),
        ranked("c", 0.7, 10),
    ]
    verifier = FixedVerifier([result("a", 0.5), result("b", 0.5)])
    output = VerificationReranker(verifier, top_n=2).rerank(
        demo_scenes()[0],
        items,
    )

    assert verifier.calls == [["a", "b"]]
    assert output[-1].segment.unit.unit_id == "c"
    assert output[-1].status == "outside-top-n"


def test_provider_failure_preserves_retrieval_order():
    items = [ranked("a", 0.9, 0), ranked("b", 0.8, 5)]
    output = VerificationReranker(BrokenVerifier()).rerank(
        demo_scenes()[0],
        items,
    )

    assert [item.segment.unit.unit_id for item in output] == ["a", "b"]
    assert all(item.status == "provider-fallback" for item in output)


def test_low_confidence_result_does_not_change_base_score():
    items = [ranked("a", 0.9, 0)]
    verifier = FixedVerifier([result("a", 0.0, confidence=0.2)])
    output = VerificationReranker(
        verifier,
        min_confidence=0.5,
    ).rerank(demo_scenes()[0], items)

    assert output[0].status == "low-confidence"
    assert output[0].final_score == 0.9


def test_malformed_provider_batch_falls_back_safely():
    items = [ranked("a", 0.9, 0), ranked("b", 0.8, 5)]
    verifier = FixedVerifier([result("a", 1.0)])
    output = VerificationReranker(verifier).rerank(demo_scenes()[0], items)

    assert [item.segment.unit.unit_id for item in output] == ["a", "b"]
    assert all(item.status == "provider-fallback" for item in output)
