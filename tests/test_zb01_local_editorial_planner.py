"""Fake Ollama only; never makes a network call or changes production search."""
import json
from io import BytesIO

import pytest

from bin_finder.models import SceneContext, SceneRecord
from bin_finder.search.query_builder import build_scene_queries
from bin_finder.search.semantic_intents import StoryCapsule
from bin_finder.search.semantic_planner import (
    EditorialPlannerError, LocalEditorialPlanner, OllamaEditorialConfig,
)

SCRIPT = "At ten at night, office lights still glow in Lujiazui, Shanghai."


def scene():
    return SceneRecord(scene_id="scene_001", order=1, english_text=SCRIPT,
                       context=SceneContext(keywords=("office lights",)))


def valid_plan():
    return {
        "scene_id": "scene_001", "narration_text": SCRIPT,
        "visual_goal": "Office towers lit after dark",
        "required_entities": ["Lujiazui"],
        "must_show": ["night office towers"],
        "must_not_show": ["daytime shops"],
        "queries": ["Lujiazui office towers night", "Lujiazui skyline lights"],
        "uncertainty": "Lights do not prove workers are present",
        "provenance": "script",
    }


class FakeReply:
    def __init__(self, value):
        self.buffer = BytesIO(value)

    def read(self, size):
        return self.buffer.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, content, *, raw=False):
        self.content, self.raw, self.calls = content, raw, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        envelope = (self.content if self.raw else {
            "message": {"content": json.dumps(self.content)}
        })
        return FakeReply(json.dumps(envelope).encode("utf-8"))


def test_query_producer_fake_local_request_and_validation():
    fake = FakeOpener(valid_plan())
    planner = LocalEditorialPlanner(opener=fake)
    assert not fake.calls
    assert planner.suggest_queries(scene(), full_script=SCRIPT) == valid_plan()["queries"]
    req, timeout = fake.calls[0]
    assert req.full_url == "http://127.0.0.1:11434/api/chat"
    assert req.get_method() == "POST" and timeout == 120
    assert json.loads(req.data)["messages"][1]["role"] == "user"
    assert json.loads(req.data)["model"] == "qwen3-vl:4b-instruct"


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:11434", "http://example.com",
    "http://127.0.0.1:11434/api/chat",
    "http://localhost:11434@evil.example",
    "http://127.0.0.1:11434?token=x",
    "http://127.0.0.1:11434/#x",
])
def test_reject_nonlocal_and_unexpected_endpoints(url):
    with pytest.raises(EditorialPlannerError):
        LocalEditorialPlanner(OllamaEditorialConfig(url=url))


def test_unsupported_named_entity_falls_back_without_side_effects():
    bad = valid_plan()
    bad["required_entities"] = ["Beijing"]
    fake = FakeOpener(bad)
    planner = LocalEditorialPlanner(opener=fake)
    baseline = build_scene_queries(scene())
    assert planner.suggest_queries(scene(), full_script=SCRIPT) == baseline
    assert len(fake.calls) == 1


@pytest.mark.parametrize("envelope", [
    {"message": {"content": "invalid-json"}},
    {"message": {"content": "x" * 66_000}},
])
def test_bad_model_reply_falls_back(envelope):
    planner = LocalEditorialPlanner(opener=FakeOpener(envelope, raw=True))
    assert planner.suggest_queries(scene(), full_script=SCRIPT) == build_scene_queries(scene())


def test_long_script_requires_capsule_rather_than_silent_truncation():
    script = SCRIPT + " This is background context." * 300
    fake = FakeOpener(valid_plan())
    planner = LocalEditorialPlanner(opener=fake)
    assert planner.suggest_queries(scene(), full_script=script) == build_scene_queries(scene())
    assert not fake.calls
    capsule = StoryCapsule(summary="Lujiazui nightlife", central_message="Office lights", arc="")
    assert planner.suggest_queries(scene(), full_script=script, capsule=capsule) == valid_plan()["queries"]


def test_limit_is_bounded_and_empty_script_never_calls_model():
    fake = FakeOpener(valid_plan())
    planner = LocalEditorialPlanner(opener=fake)
    assert planner.suggest_queries(scene(), full_script="", max_queries=3) == build_scene_queries(scene())
    assert not fake.calls
    assert planner.suggest_queries(scene(), full_script=SCRIPT, max_queries=1) == valid_plan()["queries"][:1]
    with pytest.raises(EditorialPlannerError):
        OllamaEditorialConfig(num_ctx=1024).validate()
    with pytest.raises(EditorialPlannerError):
        OllamaEditorialConfig(model="model with spaces").validate()


def test_diagnostics_identify_thinking_token_exhaustion_without_exposing_text():
    envelope = {
        "message": {"content": "", "thinking": "PRIVATE REASONING"},
        "done_reason": "length", "prompt_eval_count": 240,
        "eval_count": 4096,
    }
    diagnostics = {"old_key": "must-clear"}
    planner = LocalEditorialPlanner(opener=FakeOpener(envelope, raw=True))
    assert planner.propose(scene(), full_script=SCRIPT, diagnostics=diagnostics) is None
    assert diagnostics == {
        "done_reason": "length", "prompt_eval_count": 240,
        "eval_count": 4096, "thinking_present": True,
        "content_chars": 0, "reason": "empty-content",
    }
    assert "PRIVATE REASONING" not in repr(diagnostics)


def test_diagnostics_identify_schema_rejection():
    bad = valid_plan()
    bad["required_entities"] = ["Beijing"]
    diagnostics = {}
    planner = LocalEditorialPlanner(opener=FakeOpener(bad))
    assert planner.propose(scene(), full_script=SCRIPT, diagnostics=diagnostics) is None
    assert diagnostics["reason"] == "invalid-intent:unsupported-required-entity"
    assert diagnostics["content_chars"] > 0


def test_diagnostics_report_valid_response_without_model_content():
    diagnostics = {}
    planner = LocalEditorialPlanner(opener=FakeOpener(valid_plan()))
    result = planner.propose(scene(), full_script=SCRIPT, diagnostics=diagnostics)
    assert result["queries"] == valid_plan()["queries"]
    assert diagnostics["reason"] == "valid"
    assert "Lujiazui office towers night" not in repr(diagnostics)


def test_query_planner_uses_instruct_by_default_without_external_dependencies():
    # F021 remains a separate PR and is intentionally not imported here.
    assert OllamaEditorialConfig().model == "qwen3-vl:4b-instruct"
    assert OllamaEditorialConfig(model="qwen3-vl:4b-instruct").validate().startswith("http://")


def test_bounded_rejected_preview_is_opt_in_and_never_captures_script_or_thinking():
    bad = valid_plan()
    bad["required_entities"] = ["Beijing"]
    bad["scene_anchor"] = "office lights"
    bad["evidence_type"] = "direct"
    bad["private_extra"] = "DO_NOT_EXPOSE_PRIVATE_TEXT"
    diagnostic = {}
    planner = LocalEditorialPlanner(opener=FakeOpener(bad))
    assert planner.propose(scene(), full_script=SCRIPT, diagnostics=diagnostic) is None
    assert diagnostic["reason"] == "invalid-intent:unsupported-required-entity"
    assert "rejected_plan_preview" not in diagnostic

    diagnostic = {}
    assert planner.propose(
        scene(), full_script=SCRIPT, diagnostics=diagnostic,
        inspect_rejection=True,
    ) is None
    preview = diagnostic["rejected_plan_preview"]
    assert preview["required_entities"] == ["Beijing"]
    assert preview["queries"] == valid_plan()["queries"]
    assert "narration_text" not in preview
    assert "private_extra" not in preview
    assert "DO_NOT_EXPOSE_PRIVATE_TEXT" not in repr(diagnostic)


def test_rejection_preview_stays_bounded_on_untrusted_values():
    from bin_finder.search.semantic_planner import _bounded_rejected_preview

    bad = valid_plan()
    bad["required_entities"] = ["Beijing"]
    bad["queries"] = ["X" * 100_000]
    bad["scene_anchor"] = "Y" * 100_000
    preview = _bounded_rejected_preview(bad)
    assert "queries" not in preview
    assert "scene_anchor" not in preview
    assert preview["required_entities"] == ["Beijing"]



def test_rejected_field_shapes_expose_only_type_not_content():
    from bin_finder.search.semantic_planner import _bounded_rejected_preview

    rejected = {
        "narration_text": "PRIVATE INPUT NEVER EXPOSE",
        "queries": ["fixed subject search"],
        "required_entities": None,
        "must_show": {"unexpected": "SECRET MARKER"},
        "must_not_show": ["unobservable proof claim"],
    }
    preview = _bounded_rejected_preview(rejected)
    assert preview["field_shapes"] == {
        "queries": "list:1",
        "required_entities": "null",
        "must_show": "object",
        "must_not_show": "list:1",
    }
    assert "narration_text" not in preview
    assert "PRIVATE INPUT" not in repr(preview)
    assert "SECRET MARKER" not in repr(preview)
    assert "must_show" not in (
        k for k in preview if k != "field_shapes"
    )



def test_schema_opt_in_bounds_output_but_default_stays_json():
    from bin_finder.search.semantic_planner import EDITORIAL_JSON_SCHEMA

    fake_default = FakeOpener(valid_plan())
    default_planner = LocalEditorialPlanner(opener=fake_default)
    assert default_planner.suggest_queries(scene(), full_script=SCRIPT) == valid_plan()["queries"]
    req, _ = fake_default.calls[0]
    assert json.loads(req.data)["format"] == "json"

    fake_schema = FakeOpener(valid_plan())
    planner = LocalEditorialPlanner(
        OllamaEditorialConfig(structured_output=True), opener=fake_schema,
    )
    assert planner.suggest_queries(scene(), full_script=SCRIPT) == valid_plan()["queries"]
    req, _ = fake_schema.calls[0]
    payload = json.loads(req.data)
    assert payload["format"] == EDITORIAL_JSON_SCHEMA
    assert payload["format"]["properties"]["queries"]["maxItems"] == 3
    assert payload["format"]["properties"]["must_show"]["maxItems"] == 6
    assert payload["format"]["properties"]["evidence_type"]["enum"][-1] == "no_match"
    assert payload["stream"] is False

    with pytest.raises(EditorialPlannerError, match="invalid-structured-output"):
        OllamaEditorialConfig(structured_output="True").validate()


def test_schema_mode_keeps_local_validator_and_fallback():
    bad = valid_plan()
    bad["queries"] = ["Lujiazui" for _ in range(4)]
    fake = FakeOpener(bad)
    planner = LocalEditorialPlanner(
        OllamaEditorialConfig(structured_output=True), opener=fake,
    )
    assert planner.suggest_queries(scene(), full_script=SCRIPT) == build_scene_queries(scene())
    assert len(fake.calls) == 1
