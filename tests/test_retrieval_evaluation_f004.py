from bin_finder.demo_data import demo_scenes
from bin_finder.retrieval.engine import HybridRetrievalEngine
from bin_finder.retrieval.evaluation import RetrievalEvalCase, evaluate_retrieval
from bin_finder.retrieval.models import RetrievalUnit


def test_retrieval_evaluation_reports_top1_recall_and_mrr():
    scene = demo_scenes()[0]
    cases = (
        RetrievalEvalCase(
            case_id="cuba-mechanic",
            scene=scene,
            units=(
                RetrievalUnit("wrong", "a.mp4", 0, 5, "airport family goodbye"),
                RetrievalUnit("right", "a.mp4", 5, 10, "Havana mechanic classic Chevrolet"),
            ),
            relevant_unit_ids=frozenset({"right"}),
        ),
    )

    summary = evaluate_retrieval(HybridRetrievalEngine(), cases, k=2)

    assert summary.case_count == 1
    assert summary.top1_accuracy == 1.0
    assert summary.recall_at_k == 1.0
    assert summary.mean_reciprocal_rank == 1.0


def test_retrieval_evaluation_rejects_empty_ground_truth():
    import pytest

    case = RetrievalEvalCase(
        case_id="bad",
        scene=demo_scenes()[0],
        units=(RetrievalUnit("x", "a.mp4", 0, 5, "anything"),),
        relevant_unit_ids=frozenset(),
    )
    with pytest.raises(ValueError, match="no relevant unit ids"):
        evaluate_retrieval(HybridRetrievalEngine(), [case])
