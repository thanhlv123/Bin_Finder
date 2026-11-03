from dataclasses import replace
import json
import socket
import pytest
from bin_finder.brief import BriefConfig, BriefPlan, ShotBrief, plan_briefs, split_cues
from bin_finder.brief.providers import HeuristicBriefProvider, OllamaBriefProvider, OpenAICompatibleBriefProvider

SCRIPT = "## INTRO\nA doctor reads the report carefully. The patient walks through a quiet garden. A nurse holds a sample bottle."


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("network forbidden in brief tests")
    monkeypatch.setattr(socket.socket, "connect", forbidden)


def rows(config, cues):
    return [{k:v for k,v in b.to_dict().items() if k != "origin"}
            for b in HeuristicBriefProvider(config).propose(cues, {"cues": cues})]


def test_heuristic_complete_deterministic():
    config = BriefConfig(provider="heuristic", style_hint="bright natural light")
    plan = plan_briefs(SCRIPT, config)
    assert plan == plan_briefs(SCRIPT, config)
    assert BriefPlan.from_dict(plan.to_dict()) == plan
    assert plan.fallback_count == 0
    assert len(plan.cues) == len(plan.briefs) == 3
    for brief in plan.briefs:
        assert ShotBrief.from_dict(brief.to_dict()) == brief
        assert set(brief.queries) == set(config.sources)
        for source, queries in brief.queries.items():
            assert 1 <= len(queries) <= 3
            assert all(2 <= len(q.split()) <= 6 for q in queries)
            if source == "youtube":
                assert all("b-roll" in q for q in queries)


def test_ollama_valid_batches_and_neighbors():
    config = BriefConfig(provider="ollama", batch_size=1)
    cues = split_cues(SCRIPT)
    calls = []
    def client(url, payload, **kwargs):
        calls.append(payload)
        user = json.loads(payload["messages"][1]["content"])
        selected = [c for c in cues if c.cue_id in [r["cue_id"] for r in user["requested"]]]
        return {"message":{"content":json.dumps({"briefs": rows(config, selected)})}}
    provider = OllamaBriefProvider(config, client)
    plan = plan_briefs(SCRIPT, config, provider)
    assert plan.fallback_count == 0
    assert all(b.origin == "llm:" + config.ollama_model for b in plan.briefs)
    assert len(calls) == 3 and calls[0]["stream"] is False
    assert isinstance(calls[0]["format"], dict)
    assert len(json.loads(calls[1]["messages"][1]["content"])["context"]) == 3


@pytest.mark.parametrize("kind", ["missing", "invalid", "duplicate", "broken"])
def test_per_cue_fallback(kind):
    config = BriefConfig(provider="ollama")
    cues = split_cues(SCRIPT)
    data = rows(config, cues)
    if kind == "missing":
        data.pop(1)
    elif kind == "invalid":
        del data[1]["subject"]
    elif kind == "duplicate":
        data.append(data[1])
    def client(*args, **kwargs):
        return {"message":{"content":"{" if kind == "broken" else json.dumps({"briefs":data})}}
    plan = plan_briefs(SCRIPT, config, OllamaBriefProvider(config, client))
    assert plan.fallback_count == (3 if kind == "broken" else 1)
    assert plan.briefs[1].origin == "heuristic"
    assert "Fallback:" in plan.briefs[1].notes
    if kind != "broken":
        assert plan.briefs[0].origin.startswith("llm:")


@pytest.mark.parametrize("error", [ConnectionError, TimeoutError])
def test_transport_failure_no_secrets(error, caplog, capsys):
    config = BriefConfig(provider="openai_compatible", api_key="test-secret-987", api_base_url="https://example.test/v1", api_model="test")
    def client(*args, **kwargs):
        raise error(config.api_key)
    plan = plan_briefs(SCRIPT, config, OpenAICompatibleBriefProvider(config, client))
    assert plan.fallback_count == 3
    assert all("Fallback:" in b.notes for b in plan.briefs)
    assert config.api_key not in repr(config) + json.dumps(plan.to_dict()) + caplog.text + capsys.readouterr().out


def test_api_valid_and_key_echo_rejected():
    config = BriefConfig(provider="openai_compatible", api_key="test-secret-987", api_base_url="https://example.test/v1", api_model="test")
    cues = split_cues(SCRIPT)
    data = rows(config, cues)
    data[1]["notes"] = config.api_key
    data[0]["queries"]["pexels"] = ["", "doctor report", "DOCTOR REPORT", "a b c d e f g"]
    data[0]["queries"]["unknown"] = ["ignore source"]
    def client(url, payload, **kwargs):
        assert url.endswith("/v1/chat/completions")
        assert payload["response_format"]["type"] == "json_schema"
        assert kwargs["headers"]["Authorization"] == "Bearer " + config.api_key
        return {"choices":[{"message":{"content":json.dumps({"briefs":data})}}]}
    plan = plan_briefs(SCRIPT, config, OpenAICompatibleBriefProvider(config, client))
    assert plan.fallback_count == 1
    assert plan.briefs[0].origin == "llm:test"
    assert plan.briefs[0].queries["pexels"] == ["doctor report", "a b c d e f"]
    assert "unknown" not in plan.briefs[0].queries
    assert config.api_key not in json.dumps(plan.to_dict())


def test_auto_selection(monkeypatch):
    config = BriefConfig()
    monkeypatch.setattr(OllamaBriefProvider, "available", lambda self: False)
    assert plan_briefs(SCRIPT, config).fallback_count == 3
    assert plan_briefs(SCRIPT, config).provider_used == "heuristic"
    monkeypatch.setattr(OllamaBriefProvider, "available", lambda self: True)
    monkeypatch.setattr(OllamaBriefProvider, "request", lambda self,*args: json.dumps({"briefs":rows(config, split_cues(SCRIPT))}))
    assert plan_briefs(SCRIPT, config).provider_used == "ollama"
    monkeypatch.setattr(OllamaBriefProvider, "available", lambda self: False)
    api = replace(config, api_base_url="https://example.test/v1", api_model="test", api_key="secret")
    assert plan_briefs(SCRIPT, api).provider_used == "openai_compatible"


def test_connection_failure_stops_remaining_batches():
    config = BriefConfig(provider="ollama", batch_size=1)
    calls = []
    def client(*args, **kwargs):
        calls.append(1)
        raise ConnectionError("unavailable")
    plan = plan_briefs(SCRIPT, config, OllamaBriefProvider(config, client))
    assert len(calls) == 1
    assert plan.fallback_count == 3
    assert all("Fallback:" in b.notes for b in plan.briefs)


def test_missing_api_configuration_never_calls_client():
    config = BriefConfig(provider="openai_compatible")
    def client(*args, **kwargs):
        pytest.fail("incomplete API configuration must not send requests")
    plan = plan_briefs(SCRIPT, config, OpenAICompatibleBriefProvider(config, client))
    assert plan.fallback_count == 3
