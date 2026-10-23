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


def test_query_planner_model_is_independent_of_f021_vlm_default():
    from bin_finder.verification.ollama_vlm import DEFAULT_MODEL

    assert OllamaEditorialConfig().model == "qwen3-vl:4b-instruct"
    assert DEFAULT_MODEL == "qwen3-vl:4b"
    assert OllamaEditorialConfig(model="qwen3-vl:4b-instruct").validate().startswith("http://")
