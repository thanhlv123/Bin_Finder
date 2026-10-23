"""CLI must never contact Ollama without an explicit approval flag."""
from bin_finder.search import semantic_smoke


def test_not_approved_exits_without_construction(monkeypatch, capsys):
    class ForbiddenPlanner:
        def __init__(self):
            raise AssertionError("Ollama must not be contacted")

    monkeypatch.setattr(semantic_smoke, "LocalEditorialPlanner", ForbiddenPlanner)
    assert semantic_smoke.main([]) == 0
    assert "SKIPPED_ZB01_NOT_APPROVED" in capsys.readouterr().out


def test_explicit_smoke_handles_invalid_model_result(monkeypatch, capsys):
    class EmptyPlanner:
        def propose(self, scene, *, full_script):
            return None

    monkeypatch.setattr(semantic_smoke, "LocalEditorialPlanner", EmptyPlanner)
    assert semantic_smoke.main(["--approve-local-planner"]) == 2
    assert "ZB01_FALLBACK" in capsys.readouterr().out


def test_explicit_smoke_only_reports_validated_sample(monkeypatch, capsys):
    class SamplePlanner:
        def propose(self, scene, *, full_script):
            return {
                "queries": ["Lujiazui office towers night"],
                "must_show": ["towers after dark"],
                "must_not_show": ["daylight"],
                "uncertainty": "No evidence of overtime",
            }

    monkeypatch.setattr(semantic_smoke, "LocalEditorialPlanner", SamplePlanner)
    assert semantic_smoke.main(["--approve-local-planner"]) == 0
    output = capsys.readouterr().out
    assert "ZB01_VALID_STRUCTURED_RESULT" in output
    assert "Lujiazui office towers night" in output
