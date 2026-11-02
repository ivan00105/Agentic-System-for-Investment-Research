"""Explicit paid checks run against an in-process HTTP transport, never a provider."""

import hashlib
import json
import re
import time
from decimal import Decimal

import httpx
import pytest
from openai import OpenAI
from pydantic import ValidationError

from research_assistant import research
from research_assistant.application import Application
from research_assistant.contracts import DomainError, RunRequest
from research_assistant.fixtures import FIXTURE_CUTOFF, seed
from research_assistant.store import Store


@pytest.fixture(autouse=True)
def isolated_credentials(monkeypatch):
    for name in (
        "SEC_USER_AGENT", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "RESEARCH_MODEL",
        "RESEARCH_MODEL_PROVIDER", "OPENAI_BASE_URL", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    def forbidden(*args, **kwargs):
        pytest.fail("A test attempted an unmocked provider call")

    monkeypatch.setattr("research_assistant.application.OpenAI", forbidden)
    monkeypatch.setattr(research, "retrieve_company", forbidden)
    monkeypatch.setattr("research_assistant.application.retrieve_company", forbidden)


@pytest.fixture
def app(tmp_path):
    store = Store(tmp_path)
    seed(store)
    application = Application(store)
    try:
        yield application
    finally:
        application.close()


def check_request(**changes):
    return RunRequest(**{
        "mode": "frozen", "ticker": "MSFT", "cutoff": FIXTURE_CUTOFF,
        "source_run_id": "example-msft", "model_analysis": True,
        "connection_check": "model", **changes,
    })


def wait_for_run(app, run_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = app.store.get(run_id)
        if result.status not in {"queued", "running"}:
            return result
        time.sleep(.01)
    pytest.fail("Mock model run did not finish")


def submit(app, request=None, key=None):
    accepted = app.submit(request or check_request(), key or f"model-check-{time.monotonic_ns()}")
    return wait_for_run(app, accepted.id)


def response_body(output, *, usage=True, status="completed", model="provider/actual-model"):
    body = {
        "id": "resp-test", "object": "response", "created_at": 1700000000,
        "status": status, "model": model,
        "output": [{
            "id": "msg-test", "type": "message", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": json.dumps(output), "annotations": []}],
        }],
    }
    if usage is True:
        body["usage"] = {
            "input_tokens": 11, "output_tokens": 7, "total_tokens": 18,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0}, "cost": .0012,
        }
    elif usage is not False:
        body["usage"] = usage
    return body


def wire_model(monkeypatch, responses=None, *, usage=True):
    """Keep SDK parsing, request serialization and retry policy real."""
    monkeypatch.setenv("RESEARCH_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-router-key")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-openai-key")
    monkeypatch.setenv("RESEARCH_MODEL", "vendor/requested-model")
    monkeypatch.setenv("OPENAI_ORG_ID", "private-org")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "private-project")
    requests = []
    constructors = []
    default_outputs = [
        {"interpretations": [{"statement": "Margin needs business context.", "evidence_ids": ["fixture-MSFT-annual"]}]},
        {"objections": []},
    ]

    def handler(request):
        requests.append(request)
        index = len(requests) - 1
        if responses is not None:
            selected = responses[min(index, len(responses) - 1)]
            if isinstance(selected, Exception):
                raise selected
            return selected
        return httpx.Response(200, json=response_body(default_outputs[index % 2], usage=usage))

    def client(**kwargs):
        constructors.append(kwargs.copy())
        return OpenAI(http_client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)

    monkeypatch.setattr("research_assistant.application.OpenAI", client)
    return requests, constructors


def assert_saved_financials(app, result):
    assert result.report is not None
    source = app.store.get("example-msft").report.companies[0]
    company = result.report.companies[0]
    assert company.metrics == source.metrics
    assert company.forecast.status == "unavailable"
    assert app.store.all_evidence(result.id) == app.store.all_evidence("example-msft")
    return company


def test_openrouter_check_sends_strict_bounded_requests_and_persists_metadata(app, monkeypatch):
    requests, constructors = wire_model(monkeypatch)
    result = submit(app)
    assert result.status == "completed"
    company = assert_saved_financials(app, result)
    assert company.review_status == "completed"
    assert len(requests) == len(constructors) == 2
    for index, (request, settings) in enumerate(zip(requests, constructors)):
        assert str(request.url) == "https://openrouter.ai/api/v1/responses"
        assert request.headers["authorization"] == "Bearer secret-router-key"
        assert not request.headers.get("openai-organization")
        assert not request.headers.get("openai-project")
        assert settings["max_retries"] == 0 and "timeout" not in settings
        payload = json.loads(request.content)
        assert payload["input"][0]["role"] == "system"
        if index == 0:
            # Interpretation text remains identical to the pre-extraction prompt.
            assert hashlib.sha256(payload["input"][0]["content"].encode("utf-8")).hexdigest() == "51263fd195442cd89ffa48ca3fca6b64469f9fce7c1050bc7b8043828de862a3"
        else:
            assert "claims[].id" in payload["input"][0]["content"]
            assert "evidence[].id" in payload["input"][0]["content"]
            assert "do not interchange them" in payload["input"][0]["content"]
        assert payload["model"] == "vendor/requested-model"
        assert payload["store"] is False
        assert payload["provider"] == {"require_parameters": True, "allow_fallbacks": False}
        assert "max_output_tokens" not in payload
        assert not payload.get("tools")
        format_ = payload["text"]["format"]
        assert format_["type"] == "json_schema" and format_["strict"] is True
        assert format_["schema"]["additionalProperties"] is False
        if index == 0:
            statement = format_["schema"]["$defs"]["Interpretation"]["properties"]["statement"]
            for prose in ("Margin is 20 percent.", "The 10-K needs context.", "For 2025, margin needs context."):
                assert re.fullmatch(statement["pattern"], prose) is None
            assert re.fullmatch(statement["pattern"], "The annual filing needs business context.")
        packet = json.loads(payload["input"][1]["content"])
        assert {item["id"] for item in packet["evidence"]} == {"fixture-MSFT-annual"}
        if index == 1:
            fields = format_["schema"]["$defs"]["CompanyObjection"]["properties"]
            assert fields["claim_id"]["enum"] == sorted(c["id"] for c in packet["claims"])
            assert fields["evidence_ids"]["items"]["enum"] == sorted(e["id"] for e in packet["evidence"])
    assert result.report.model_run.provider == "openrouter"
    assert result.report.model_run.model == "vendor/requested-model"
    assert result.report.model_run.schema_version == "financial-review-v3"
    assert result.report.model_run.max_output_tokens is None
    assert len(result.report.model_calls) == 2
    for call in result.report.model_calls:
        assert call.provider == "openrouter" and call.requested_model == "vendor/requested-model"
        assert call.returned_model == "provider/actual-model"
        assert call.response_id == "resp-test" and call.status == "completed"
        assert (call.input_tokens, call.output_tokens, call.total_tokens) == (11, 7, 18)
        assert call.cost_usd == Decimal("0.0012")
    check = app.connections()["model"].check
    assert check.status == "passed" and check.run_id == result.id and check.checked_at
    assert "secret-router-key" not in result.model_dump_json()


def test_missing_usage_and_returned_model_remain_unknown(app, monkeypatch):
    responses = [
        httpx.Response(200, json=response_body({"interpretations": []}, usage=False, model=None)),
        httpx.Response(200, json=response_body({"objections": []}, usage=False, model=None)),
    ]
    requests, _ = wire_model(monkeypatch, responses)
    result = submit(app)
    assert result.report.companies[0].review_status == "completed" and len(requests) == 2
    for call in result.report.model_calls:
        assert call.returned_model is None
        assert call.input_tokens is call.output_tokens is call.total_tokens is call.cost_usd is None


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 429, 500])
def test_provider_failure_is_not_retried_and_keeps_financials(app, monkeypatch, status):
    requests, _ = wire_model(monkeypatch, [httpx.Response(status, json={
        "error": {"message": "secret-router-key private-provider-body", "type": "provider_error"},
    })])
    result = submit(app)
    company = assert_saved_financials(app, result)
    assert company.review_status == "failed" and len(requests) == 1
    assert app.connections()["model"].check.status == "failed"
    assert len(result.report.model_calls) == 1
    call = result.report.model_calls[0]
    assert call.status == "failed" and call.error_code
    assert call.cost_usd is None and call.total_tokens is None
    assert "secret-router-key" not in result.model_dump_json()
    assert "private-provider-body" not in result.model_dump_json()


def test_timeout_is_not_retried_or_reported_as_zero_cost(app, monkeypatch):
    requests, _ = wire_model(monkeypatch, [httpx.ReadTimeout("secret-router-key")])
    result = submit(app)
    assert assert_saved_financials(app, result).review_status == "failed"
    assert len(requests) == 1
    assert result.report.model_calls[0].cost_usd is None
    assert result.report.model_calls[0].error_code == "model_timeout"


@pytest.mark.parametrize("refusal", [False, True])
@pytest.mark.parametrize("call_index", [0, 1], ids=["interpretation", "critic"])
def test_incomplete_and_refused_responses_never_pass_check(app, monkeypatch, refusal, call_index):
    output = {"interpretations": []} if call_index == 0 else {"objections": []}
    body = response_body(output, status="completed" if refusal else "incomplete")
    if refusal:
        body["output"][0]["content"] = [{"type": "refusal", "refusal": "Cannot review."}]
    else:
        body["incomplete_details"] = {"reason": "max_output_tokens"}
        body["usage"].update(output_tokens=2000, total_tokens=2011)
        body["usage"]["output_tokens_details"]["reasoning_tokens"] = 1900
    responses = [httpx.Response(200, json=response_body({"interpretations": [{
        "statement": "Margin needs business context.", "evidence_ids": ["fixture-MSFT-annual"],
    }]}))] if call_index else []
    responses.append(httpx.Response(200, json=body))
    requests, _ = wire_model(monkeypatch, responses)
    result = submit(app)
    company = assert_saved_financials(app, result)
    assert company.review_status == "failed"
    assert len(requests) == call_index + 1 and app.connections()["model"].check.status == "failed"
    if call_index:
        assert result.report.model_calls[0].status == "completed"
        assert any(claim.statement == "Margin needs business context." for claim in company.claims)
    call = result.report.model_calls[call_index]
    assert call.status == "incomplete" and call.error_code == ("model_incomplete" if refusal else "model_output_limit")
    assert call.provider_status == ("completed" if refusal else "incomplete")
    assert call.reasoning_tokens == (0 if refusal else 1900)
    assert call.incomplete_reason == (None if refusal else "max_output_tokens")
    assert call.total_tokens == (18 if refusal else 2011) and call.cost_usd == Decimal("0.0012")


def test_legacy_allowance_does_not_stop_critic_and_cost_is_still_saved(app, monkeypatch):
    requests, _ = wire_model(monkeypatch)
    result = submit(app, check_request(spending_limit_usd="0.001"))
    assert result.status == "completed"
    assert assert_saved_financials(app, result).review_status == "completed"
    assert len(requests) == len(result.report.model_calls) == 2
    assert result.report.model_calls[0].status == "completed"
    assert result.report.model_calls[0].cost_usd == Decimal("0.0012")
    assert app.connections()["model"].check.status == "passed"


@pytest.mark.parametrize("cost", [None, "NaN", "-0.1", "unreported"])
def test_unusable_provider_cost_stays_unknown(app, monkeypatch, cost):
    requests, _ = wire_model(monkeypatch, usage={
        "input_tokens": 11, "output_tokens": 7, "total_tokens": 18,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens_details": {"reasoning_tokens": 0}, "cost": cost,
    })
    result = submit(app)
    assert result.report.companies[0].review_status == "completed" and len(requests) == 2
    assert all(call.cost_usd is None for call in result.report.model_calls)


@pytest.mark.parametrize("output,reason", [
    ({"interpretations": [], "unexpected": "field"}, "required schema"),
    ({"interpretations": [{"statement": "Margin is 20 percent.", "evidence_ids": ["fixture-MSFT-annual"]}]}, "numbers in a qualitative interpretation"),
    ({"interpretations": [{"statement": "The 10-K needs context.", "evidence_ids": ["fixture-MSFT-annual"]}]}, "numbers in a qualitative interpretation"),
    ({"interpretations": [{"statement": "For 2025, margin needs context.", "evidence_ids": ["fixture-MSFT-annual"]}]}, "numbers in a qualitative interpretation"),
    ({"interpretations": [{"statement": "Margin needs context.", "evidence_ids": ["unknown"]}]}, "source outside the supplied evidence"),
])
def test_schema_and_reference_failures_do_not_pass_check(app, monkeypatch, output, reason):
    requests, _ = wire_model(monkeypatch, [httpx.Response(200, json=response_body(output))])
    result = submit(app)
    company = assert_saved_financials(app, result)
    assert company.review_status == "failed"
    assert reason in company.review_error
    assert len(requests) == 1
    assert app.connections()["model"].check.status == "failed"
    assert result.report.model_calls[0].status == "failed"


@pytest.mark.parametrize("raw_output", [
    "{broken output JSON",
    '{"interpretations": [], "unexpected": "field"}',
])
def test_unparsable_output_retains_provider_usage_and_identity(app, monkeypatch, raw_output):
    body = response_body({})
    body["output"][0]["content"][0]["text"] = raw_output
    requests, _ = wire_model(monkeypatch, [httpx.Response(200, json=body)])
    result = submit(app)
    assert assert_saved_financials(app, result).review_status == "failed"
    assert len(requests) == 1 and app.connections()["model"].check.status == "failed"
    call = result.report.model_calls[0]
    assert call.status == "failed" and call.error_code == "model_schema"
    assert (call.input_tokens, call.output_tokens, call.total_tokens) == (11, 7, 18)
    assert call.cost_usd == Decimal("0.0012")
    assert call.returned_model == "provider/actual-model" and call.response_id == "resp-test"


@pytest.mark.parametrize("claim_id,evidence_ids,reason", [
    ("unknown", ["fixture-MSFT-annual"], "claim ID not supplied"),
    ("fixture-MSFT-annual", ["fixture-MSFT-annual"], "claim ID not supplied"),
    ("MSFT-margin", ["MSFT-margin"], "evidence IDs not supplied"),
    ("AAPL-margin", ["fixture-MSFT-annual"], "claim ID not supplied"),
])
def test_invalid_critic_keeps_valid_draft_and_deterministic_results(app, monkeypatch, claim_id, evidence_ids, reason):
    responses = [
        httpx.Response(200, json=response_body({"interpretations": [{
            "statement": "Margin needs context.", "evidence_ids": ["fixture-MSFT-annual"],
        }]})),
        httpx.Response(200, json=response_body({"objections": [{
            "claim_id": claim_id, "explanation": "Check source support.",
            "evidence_ids": evidence_ids, "requested_check": "source_support",
        }]})),
    ]
    requests, _ = wire_model(monkeypatch, responses)
    result = submit(app)
    company = assert_saved_financials(app, result)
    assert company.review_status == "failed" and len(requests) == 2
    assert any(c.statement == "Margin needs context." for c in company.claims)
    assert result.report.model_calls[-1].status == "failed"
    call = result.report.model_calls[-1]
    assert reason in call.error_message and call.error_message == company.review_error
    rejected = json.loads(app.store.snapshot_bytes(call.output_snapshot_hash))
    assert rejected["objections"][0]["claim_id"] == claim_id
    assert rejected["objections"][0]["evidence_ids"] == evidence_ids
    assert app.connections()["model"].check.status == "failed"


def test_duplicate_check_and_replay_make_no_additional_calls(app, monkeypatch):
    requests, _ = wire_model(monkeypatch)
    request = check_request()
    result = submit(app, request, "paid-check-key")
    check = app.connections()["model"].check
    duplicate = submit(app, request, "paid-check-key")
    assert duplicate.id == result.id and len(requests) == 2
    with pytest.raises(DomainError) as conflict:
        app.submit(check_request(spending_limit_usd="0.20"), "paid-check-key")
    assert conflict.value.code == "idempotency_conflict"
    replay = submit(app, check_request(
        mode="replay", source_run_id=result.id, connection_check=None,
        spending_limit_usd=None, provider_limit_confirmed=False,
    ))
    assert replay.report == result.report and len(requests) == 2
    assert app.connections()["model"].check == check


def test_financials_only_run_and_reading_configuration_never_call_model(app, monkeypatch):
    requests, constructors = wire_model(monkeypatch)
    assert app.connections()["model"].configured
    result = submit(app, check_request(
        connection_check=None, model_analysis=False, spending_limit_usd=None,
        provider_limit_confirmed=False,
    ))
    assert assert_saved_financials(app, result).review_status == "not_requested"
    assert not requests and not constructors
    assert result.report.model_run is None and result.report.model_calls == []
    assert app.connections()["model"].check.status == "not_tested"


@pytest.mark.parametrize("changes", [
    {"mode": "fresh", "source_run_id": None}, {"mode": "replay"},
    {"model_analysis": False},
    {"kind": "discovery", "ticker": None, "screen": {}},
    {"connection_check": "sec", "mode": "fresh", "source_run_id": None},
])
def test_explicit_model_check_guards_are_enforced(changes):
    with pytest.raises(ValidationError):
        check_request(**changes)


def test_model_check_needs_no_project_dollar_allowance_and_old_requests_roundtrip():
    request = check_request()
    assert RunRequest.model_validate_json(request.model_dump_json()) == request
    old = check_request(spending_limit_usd="0.001", provider_limit_confirmed=True)
    assert RunRequest.model_validate_json(old.model_dump_json()) == old


def test_large_review_retains_complete_evidence_and_is_not_cut_off_by_prototype_caps(app, monkeypatch):
    original = app.store.all_evidence("example-msft")[0]
    long_excerpt = "Supplied disclosure context. " * 600 + "END OF COMPLETE EVIDENCE"
    ids = []
    for index in range(7):
        item = original.model_copy(update={"id": f"additional-source-{index}", "excerpt": long_excerpt})
        app.store.add_evidence("example-msft", item)
        ids.append(item.id)
    statement = "Margin alone needs business context. " * 60
    draft = {"interpretations": [{"statement": statement, "evidence_ids": ids} for _ in range(4)]}
    critique = {"objections": [{
        "claim_id": "MSFT-interpretation-0", "explanation": "Inspect the supplied source support. " * 60,
        "evidence_ids": ids, "requested_check": "source_support",
    } for _ in range(6)]}
    usage = {"input_tokens": 20000, "output_tokens": 6000, "total_tokens": 26000,
             "output_tokens_details": {"reasoning_tokens": 5000}}
    responses = [httpx.Response(200, json=response_body(output, usage=usage)) for output in (draft, critique)]
    requests, _ = wire_model(monkeypatch, responses)
    result = submit(app)
    company = assert_saved_financials(app, result)
    assert result.status == "completed" and company.review_status == "completed"
    assert len(company.reviews) == 6
    assert sum(claim.kind == "interpretation" for claim in company.claims) == 4
    assert all(call.total_tokens == 26000 and call.reasoning_tokens == 5000 for call in result.report.model_calls)
    for request in requests:
        payload = json.loads(request.content)
        assert "max_output_tokens" not in payload
        packet = json.loads(payload["input"][1]["content"])
        assert all(item["excerpt"] == long_excerpt for item in packet["evidence"] if item["id"] in ids)


@pytest.mark.parametrize("reason,code", [("content_filter", "model_content_filter"), ("private-provider-value", "model_incomplete")])
def test_provider_stop_reason_is_safe_and_saved_even_without_parseable_json(app, monkeypatch, reason, code):
    body = response_body({}, status="incomplete")
    body["incomplete_details"] = {"reason": reason}
    body["output"][0]["content"][0]["text"] = "{unfinished JSON"
    requests, _ = wire_model(monkeypatch, [httpx.Response(200, json=body)])
    result = submit(app)
    call = result.report.model_calls[0]
    assert call.status == "incomplete" and call.error_code == code
    assert call.incomplete_reason == (reason if reason == "content_filter" else "other")
    assert "private-provider-value" not in result.model_dump_json()
    assert len(requests) == 1
    assert assert_saved_financials(app, result).review_status == "failed"


def test_provider_context_limit_is_reported_without_truncating_or_retrying(app, monkeypatch):
    requests, _ = wire_model(monkeypatch, [httpx.Response(400, json={
        "error": {"message": "private-provider-body", "type": "invalid_request_error", "code": "context_length_exceeded"},
    })])
    result = submit(app)
    assert result.report.model_calls[0].error_code == "model_context_limit"
    assert "input context" in assert_saved_financials(app, result).review_error
    assert "private-provider-body" not in result.model_dump_json()
    assert len(requests) == 1
