"""BF-S04A.1 local text planner safety and contract gates: fully offline."""
from __future__ import annotations

import io
import json
import urllib.error
from dataclasses import replace

import pytest

from bin_finder.search.editorial_local_model import (
    LocalEditorialConfig, LocalEditorialConfigError, LocalEditorialOutcome,
    OllamaLocalEditorialPlanner, parse_local_editorial_reply,
)
from bin_finder.search.editorial_local_smoke import main, selected_excerpt
from bin_finder.search.editorial_shot_plan import EditorialShotPlanError
from bin_finder.search.editorial_shot_smoke import source_and_base, proposed_shots


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class FakeOpener:
    def __init__(self, message):
        self.calls = []
        self.message = message

    def open(self, request, timeout=None):
        self.calls.append((request, timeout))
        if isinstance(self.message, Exception):
            raise self.message
        return Response(self.message)


def draft_for_slot(slot=2):
    _, full = source_and_base()
    scenes, mini = selected_excerpt(slot)
    payload = proposed_shots(full)
    payload["source_digest"] = mini.source_digest
    payload["shots"] = [
        item for item in payload["shots"] if item["slot_id"] == f"slot{slot}"
    ]
    return scenes, mini, payload


def wrapped(value):
    return json.dumps({"message": {"content": value}}).encode("utf-8")


def fake_client(reply):
    opener = FakeOpener(wrapped(reply))
    return OllamaLocalEditorialPlanner(opener=opener), opener


def test_one_slot_editorial_draft_roundtrip_from_real_french_excerpt():
    scenes, base, draft = draft_for_slot()
    plan = parse_local_editorial_reply(
        json.dumps(draft, ensure_ascii=False), base, scenes
    )
    assert len(plan.shots) == 3
    assert all(s.slot_id == "slot2" for s in plan.shots)
    assert sum(s.target_duration_seconds for s in plan.shots) == 7
    assert all(s.factual_status == "unverified" for s in plan.shots)
    assert all(s.rights_status == "pending" for s in plan.shots)
    assert not any(s.timeline_approved for s in plan.shots)
    assert set(plan.route_counts()) == {"contextual_stock_search"}


def test_without_explicit_approval_has_no_network_even_with_fake_opener():
    scenes, base, draft = draft_for_slot()
    client, opener = fake_client(json.dumps(draft))
    result = client.propose(base, scenes)
    assert result.status == "local-model-approval-required"
    assert result.calls_attempted == 0
    assert opener.calls == []
    assert result.plan is None


def test_approved_success_is_one_loopback_text_request_and_no_media_payload():
    scenes, base, draft = draft_for_slot(1)
    client, opener = fake_client(json.dumps(draft, ensure_ascii=False))
    result = client.propose(base, scenes, approve_local_model_call=True)
    assert result.plan is not None
    assert result.status == "local-shot-plan-proposed-human-review"
    assert result.calls_attempted == 1
    assert result.confirmed_http_requests == "unknown"
    assert result.provider_calls == result.cloud_uploads == result.media_downloads == 0
    assert result.timeline_approved is False
    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert timeout == 180
    assert request.full_url == "http://127.0.0.1:11434/api/chat"
    assert request.get_method() == "POST"
    body = json.loads(request.data)
    assert body["model"] == "qwen3-vl:4b-instruct"
    assert body["stream"] is False and body["format"] == "json"
    assert body["options"] == {
        "temperature": 0, "seed": 0, "num_ctx": 8192,
        "num_predict": 4096,
    }
    assert "images" not in body["messages"][0]
    assert "Gaspard Ulliel." in body["messages"][0]["content"]
    assert "license" in body["messages"][0]["content"].lower()
    assert not any(k.lower() == "authorization" for k in request.headers)


@pytest.mark.parametrize("remote", [
    "http://example.com:11434", "http://192.168.1.9:11434",
    "https://127.0.0.1:11434", "http://localhost:11434/private",
    "http://127.0.0.1.evil.com", "http://user:pass@127.0.0.1",
])
def test_disallow_remote_untrusted_or_credentialed_model_endpoints(remote):
    with pytest.raises(ValueError):
        OllamaLocalEditorialPlanner(LocalEditorialConfig(url=remote))


@pytest.mark.parametrize("kw", [
    {"model": "cloud:latest"},
    {"num_predict": 8192},
    {"num_ctx": 2000},
    {"num_predict": -1},
    {"timeout_seconds": float("nan")},
    {"timeout_seconds": 0},
])
def test_unsupported_models_and_unbounded_settings_rejected(kw):
    with pytest.raises((LocalEditorialConfigError, ValueError)):
        OllamaLocalEditorialPlanner(LocalEditorialConfig(**kw))


@pytest.mark.parametrize("reply,reason", [
    ("", "empty-local-model-reply"),
    ("I have generated three shots", "invalid-local-model-json"),
    ("[]", "invalid-local-model-object"),
    ('{"shots":[],"shots":[]}', "invalid-local-model-json"),
    ('{"shots": NaN}', "invalid-local-model-json"),
    ('{"format":"bad","shots":[]}', "invalid-shot-format"),
])
def test_invalid_model_output_is_refused_without_auto_repair(reply, reason):
    scenes, base, _ = draft_for_slot()
    with pytest.raises(EditorialShotPlanError, match=reason):
        parse_local_editorial_reply(reply, base, scenes)


def test_forged_rights_or_event_evidence_is_rejected_after_single_request():
    scenes, base, draft = draft_for_slot(1)
    draft["shots"][0]["rights_status"] = "approved"
    client, opener = fake_client(json.dumps(draft))
    result = client.propose(base, scenes, approve_local_model_call=True)
    assert result.status == "local-model-shot-plan-rejected"
    assert result.reject_reason == "forged-rights-approval"
    assert result.plan is None
    assert len(opener.calls) == 1


def test_empty_thinking_reply_does_not_become_valid_plan():
    client, opener = fake_client("")
    scenes, base, _ = draft_for_slot()
    result = client.propose(base, scenes, approve_local_model_call=True)
    assert result.plan is None
    assert result.reject_reason == "empty-local-model-reply"
    assert len(opener.calls) == 1


def test_http_timeout_never_retries_or_leaks_details():
    opener = FakeOpener(urllib.error.URLError("SECRET_REMOTE_URL_AND_KEYS"))
    client = OllamaLocalEditorialPlanner(opener=opener)
    scenes, base, _ = draft_for_slot()
    result = client.propose(base, scenes, approve_local_model_call=True)
    assert result.status == "local-model-unavailable"
    assert result.calls_attempted == 1
    assert len(opener.calls) == 1
    assert "SECRET" not in repr(result)


def test_oversized_model_reply_is_rejected_before_json_parser():
    scenes, base, _ = draft_for_slot()
    client = OllamaLocalEditorialPlanner(
        opener=FakeOpener(b"x" * 262145),
    )
    result = client.propose(base, scenes, approve_local_model_call=True)
    assert result.status == "local-model-reply-oversized"


def test_untrusted_source_script_never_executed_or_printed_by_model_client():
    scenes, base, draft = draft_for_slot()
    different = list(scenes)
    different[0] = replace(
        different[0], english_text="$([System.IO.File]::Delete('D:/secret'))"
    )
    client, opener = fake_client(json.dumps(draft))
    with pytest.raises(EditorialShotPlanError, match="stale-source-scenes"):
        client.propose(base, different, approve_local_model_call=True)
    assert opener.calls == []


def test_cli_offline_default_and_explicit_output_does_not_write(tmp_path, capsys):
    out = tmp_path / "planned.json"
    assert main(["--slot", "2", "--output-json", str(out)]) == 0
    text = capsys.readouterr().out
    assert "BFS04A1_STATUS: local-model-approval-required" in text
    assert "BFS04A1_MODEL_CALL_ATTEMPTS: 0" in text
    assert "BFS04A1_CLOUD_UPLOADS: 0" in text
    assert not out.exists()


def test_cli_validated_proposal_written_only_to_explicit_new_json_file(
    tmp_path, capsys, monkeypatch
):
    scenes, base, draft = draft_for_slot()
    model_result = parse_local_editorial_reply(json.dumps(draft), base, scenes)
    class FakePlanner:
        def __init__(self, config): self.config = config
        def propose(self, base, scenes, *, approve_local_model_call=False):
            assert approve_local_model_call is True
            return LocalEditorialOutcome(
                "local-shot-plan-proposed-human-review", model_result,
                calls_attempted=1, confirmed_http_requests="unknown",
            )
    monkeypatch.setattr(
        "bin_finder.search.editorial_local_smoke.OllamaLocalEditorialPlanner",
        FakePlanner,
    )
    target = tmp_path / "my_shots.json"
    args = ["--slot", "2", "--approve-local-model-call",
            "--output-json", str(target)]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert target.exists()
    content = json.loads(target.read_text("utf-8"))
    assert content["status"] == "proposal-only-unverified"
    assert content["shots"][0]["rights_status"] == "pending"
    assert "BFS04A1_JSON_WRITTEN: True" in first
    assert str(tmp_path) not in first
    # No silent overwriting: the new-file requirement is checked
    # BEFORE model invocation.
    assert main(args) == 2
    err = capsys.readouterr().out
    assert "BFS04A1_MODEL_CALL_ATTEMPTS: 0" in err
    assert "BFS04A1_STATUS: invalid-local-output-target" in err


def test_cli_broken_or_remote_output_target_blocks_inference(tmp_path, capsys):
    assert main(["--approve-local-model-call",
                 "--output-json", "https://host.invalid/output.json"]) == 2
    o = capsys.readouterr().out
    assert "BFS04A1_MODEL_CALL_ATTEMPTS: 0" in o
    assert "BFS04A1_JSON_WRITTEN: True" not in o


def test_shots_only_model_output_gets_trusted_envelope_and_stays_unverified():
    scenes, base, draft = draft_for_slot(2)
    shots_only = {"shots": draft["shots"]}
    plan = parse_local_editorial_reply(
        json.dumps(shots_only, ensure_ascii=False), base, scenes
    )
    assert plan.plan_id == "bf_s04a_model_proposal"
    assert plan.base_plan_id == base.plan_id
    assert plan.source_digest == base.source_digest
    assert len(plan.shots) == 3
    assert all(s.rights_status == "pending" for s in plan.shots)
    assert all(s.factual_status == "unverified" for s in plan.shots)
    assert all(s.timeline_approved is False for s in plan.shots)


def test_shots_only_prompt_does_not_delegate_project_identity_to_model():
    from bin_finder.search.editorial_shot_prompt import make_editorial_shot_prompt
    scenes, base, _ = draft_for_slot(2)
    prompt = make_editorial_shot_prompt(base, scenes, shots_only=True)
    assert "ONLY the top-level key shots" in prompt
    assert "those identity fields are owned by the application" in prompt
    assert "ONE JSON object" in prompt
    assert "Gaspard" not in prompt  # selected Ski-Savoie slot has no actor name
    assert "en Savoie" in prompt


def test_shots_only_client_one_mock_request_and_no_ai_fallback():
    scenes, base, draft = draft_for_slot(2)
    client, opener = fake_client(
        json.dumps({"shots": draft["shots"]}, ensure_ascii=False)
    )
    result = client.propose(base, scenes, approve_local_model_call=True)
    assert len(opener.calls) == 1
    assert result.status == "local-shot-plan-proposed-human-review"
    assert result.plan is not None
    payload = json.loads(opener.calls[0][0].data)
    assert "ONLY the top-level key shots" in payload["messages"][0]["content"]
    assert "images" not in payload["messages"][0]


@pytest.mark.parametrize("top,reason", [
    ({"shots": []}, "invalid-shot-list"),
    ({"shots": [], "format": "wrong"}, "invalid-shot-format"),
    ({"shots": [], "base_plan_id": "forged"}, "invalid-shot-format"),
    ({"shots": [], "source_digest": "0" * 64}, "invalid-shot-format"),
    ({"shots": [], "rights_status": "approved"}, "invalid-shot-format"),
])
def test_partial_or_forged_wrappers_are_not_auto_repaired(top, reason):
    scenes, base, _ = draft_for_slot(2)
    with pytest.raises(EditorialShotPlanError, match="^" + reason + "$"):
        parse_local_editorial_reply(json.dumps(top), base, scenes)


def test_shots_only_does_not_fill_in_missing_shot_content():
    scenes, base, draft = draft_for_slot(2)
    rows = [dict(draft["shots"][0])]
    del rows[0]["source_anchor"]
    with pytest.raises(EditorialShotPlanError, match="^invalid-shot-anchor$"):
        parse_local_editorial_reply(json.dumps({"shots": rows}), base, scenes)


def test_shots_only_rejects_model_attempt_at_license_or_fact_verification():
    scenes, base, draft = draft_for_slot(2)
    rows = [dict(draft["shots"][0])]
    rows[0]["rights_status"] = "approved"
    with pytest.raises(EditorialShotPlanError, match="^forged-rights-approval$"):
        parse_local_editorial_reply(json.dumps({"shots": rows}), base, scenes)



@pytest.mark.parametrize("language,code", [
    ("English", "en"),
    ("ENGLISH", "en"),
    (" en ", "en"),
    ("EN", "en"),
    ("French", "fr"),
    ("français", "fr"),
    ("francais", "fr"),
    ("German", "de"),
    ("Deutsch", "de"),
    ("Spanish", "es"),
    ("español", "es"),
    ("Vietnamese", "vi"),
    ("tiếng việt", "vi"),
])
def test_known_model_language_aliases_are_canonicalized_but_not_guessed(language, code):
    scenes, base, draft = draft_for_slot(2)
    proposed = {"shots": [dict(draft["shots"][0])]}
    proposed["shots"][0]["search_queries"] = [{"language": language, "text": "ski slope"}]
    original = json.dumps(proposed, ensure_ascii=False)
    plan = parse_local_editorial_reply(original, base, scenes)
    assert plan.shots[0].search_queries[0].language == code
    assert json.dumps(proposed, ensure_ascii=False) == original


@pytest.mark.parametrize("language", [
    "en-US", "fr-FR", "Russian", "zh", "unknown", "", 5, None, ["en"],
])
def test_unsupported_or_ambiguous_language_is_still_rejected(language):
    scenes, base, draft = draft_for_slot(2)
    proposed = {"shots": [dict(draft["shots"][0])]}
    proposed["shots"][0]["search_queries"] = [{"language": language, "text": "ski slope"}]
    with pytest.raises(EditorialShotPlanError, match="^invalid-shot-language$"):
        parse_local_editorial_reply(json.dumps(proposed), base, scenes)


def test_normalized_count_is_auditable_after_one_fake_ollama_request():
    scenes, base, draft = draft_for_slot(2)
    proposed = {"shots": [dict(draft["shots"][0])]}
    proposed["shots"][0]["search_queries"] = [
        {"language": "English", "text": "gentle blue piste"},
        {"language": "French", "text": "piste bleue douce"},
    ]
    client, opener = fake_client(json.dumps(proposed, ensure_ascii=False))
    outcome = client.propose(base, scenes, approve_local_model_call=True)
    assert outcome.status == "local-shot-plan-proposed-human-review"
    assert len(opener.calls) == 1
    assert outcome.normalized_language_labels == 2
    assert outcome.plan is not None
    assert [q.language for q in outcome.plan.shots[0].search_queries] == ["en", "fr"]
    assert outcome.plan.shots[0].timeline_approved is False
    assert outcome.plan.shots[0].rights_status == "pending"


def test_unknown_language_does_not_autotranslate_or_second_request():
    scenes, base, draft = draft_for_slot(2)
    proposed = {"shots": [dict(draft["shots"][0])]}
    proposed["shots"][0]["search_queries"] = [
        {"language": "Klingon", "text": "alpine ski slope"}
    ]
    client, opener = fake_client(json.dumps(proposed, ensure_ascii=False))
    outcome = client.propose(base, scenes, approve_local_model_call=True)
    assert outcome.status == "local-model-shot-plan-rejected"
    assert outcome.reject_reason == "invalid-shot-language"
    assert outcome.plan is None
    assert outcome.normalized_language_labels == 0
    assert len(opener.calls) == 1


def test_normalization_never_rewrites_factual_claims_or_forged_license():
    scenes, base, draft = draft_for_slot(2)
    proposed = {"shots": [dict(draft["shots"][0])]}
    proposed["shots"][0]["search_queries"] = [
        {"language": "English", "text": "ski resort"}
    ]
    proposed["shots"][0]["rights_status"] = "approved"
    with pytest.raises(EditorialShotPlanError, match="^forged-rights-approval$"):
        parse_local_editorial_reply(json.dumps(proposed), base, scenes)


def test_normalization_never_fills_missing_source_anchor():
    scenes, base, draft = draft_for_slot(2)
    proposed = {"shots": [dict(draft["shots"][0])]}
    proposed["shots"][0]["search_queries"] = [
        {"language": "English", "text": "ski resort"}
    ]
    proposed["shots"][0].pop("source_anchor")
    with pytest.raises(EditorialShotPlanError, match="^invalid-shot-anchor$"):
        parse_local_editorial_reply(json.dumps(proposed), base, scenes)


def test_prompt_explicitly_requires_iso_codes_and_not_full_names():
    from bin_finder.search.editorial_shot_prompt import make_editorial_shot_prompt
    scenes, base, draft = draft_for_slot(2)
    prompt = make_editorial_shot_prompt(base, scenes, shots_only=True)
    assert "language value MUST be one exact lowercase code" in prompt
    assert "NEVER use language names English, French" in prompt
    assert "en/fr/vi/es/de" in prompt
