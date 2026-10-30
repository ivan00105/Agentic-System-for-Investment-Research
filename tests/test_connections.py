"""Connection observations use mock providers only; reading configuration never probes."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from research_assistant import research
from research_assistant.api import create_app
from research_assistant.application import Application, Budget, Critique, Draft, Interpretation, Objection
from research_assistant.contracts import ConnectionCheck, DomainError, RunRequest
from research_assistant.fixtures import FIXTURE_CUTOFF, seed
from research_assistant.store import Store


@pytest.fixture(autouse=True)
def isolated_providers(monkeypatch):
    for name in ("SEC_USER_AGENT", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "RESEARCH_MODEL_PROVIDER", "RESEARCH_MODEL", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail("A provider was called without an explicit test double")
    monkeypatch.setattr("research_assistant.application.OpenAI", forbidden)
    monkeypatch.setattr(research, "httpx", SimpleNamespace(Client=forbidden, Timeout=httpx.Timeout, HTTPError=httpx.HTTPError))


@pytest.fixture
def app(tmp_path):
    store = Store(tmp_path)
    seed(store)
    result = Application(store)
    try:
        yield result
    finally:
        result.close()


def request(**changes):
    return RunRequest(**{"mode": "frozen", "ticker": "MSFT", "cutoff": FIXTURE_CUTOFF, "source_run_id": "example-msft", **changes})


def run(app, **changes):
    result = app.submit(request(**changes), f"connections-{time.monotonic_ns()}")
    for _ in range(200):
        result = app.store.get(result.id)
        if result.status not in ("queued", "running"):
            return result
        time.sleep(.01)
    pytest.fail("Run did not finish")


def checked(app, connection, status, result):
    check = app.connections()[connection].check
    assert check.status == status
    assert check.run_id == result.id
    assert check.checked_at is not None
    assert check.checked_at.tzinfo is not None
    assert app.store.get(check.run_id).id == result.id
    return check


def sec_transport(monkeypatch, response):
    monkeypatch.setenv("SEC_USER_AGENT", "Private contact private@example.invalid")
    transport = httpx.MockTransport(lambda req: response)
    monkeypatch.setattr(research.httpx, "Client", lambda **kwargs: httpx.Client(transport=transport, **kwargs))


def model_transport(monkeypatch, failure=None):
    monkeypatch.setenv("OPENAI_API_KEY", "private-api-key")
    monkeypatch.setenv("RESEARCH_MODEL", "test-model")
    calls = []
    class Client:
        def __init__(self, **kwargs):
            self.responses = self
            self.with_raw_response = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def parse(self, **kwargs):
            calls.append(kwargs)
            if failure == "timeout":
                raise TimeoutError("private-api-key https://credential@private.invalid")
            if failure == "malformed":
                raise ValueError("private-api-key")
            if failure == "host":
                raise OSError("Unrelated local host failure")
            if failure == "incomplete":
                return SimpleNamespace(http_response=SimpleNamespace(json=lambda: {}), parse=lambda: SimpleNamespace(status="incomplete", output_parsed=None))
            if len(calls) == 1:
                output = Draft(interpretations=[Interpretation(statement="Margin needs context." if failure != "numbers" else "Margin is 20 percent.", evidence_ids=["unknown" if failure == "bad_refs" else "fixture-MSFT-annual"])])
            else:
                output = Critique(objections=[] if failure != "critic" else [Objection(claim_id="unknown", explanation="Check source.", evidence_ids=["fixture-MSFT-annual"], requested_check="source_support")])
            return SimpleNamespace(http_response=SimpleNamespace(json=lambda: {"usage": {"total_tokens": 10}}), parse=lambda: SimpleNamespace(status="completed", output_parsed=output))
    monkeypatch.setattr("research_assistant.application.OpenAI", Client)
    return calls


@pytest.mark.parametrize("sec,key,model", [(None, None, None), ("  ", "  ", "  "), ("No contact", "key", ""), ("Contact me@example.invalid", "key", "model")])
def test_config_is_presence_only_and_never_calls_providers(tmp_path, monkeypatch, sec, key, model):
    for name, value in (("SEC_USER_AGENT", sec), ("OPENAI_API_KEY", key), ("RESEARCH_MODEL", model)):
        if value is not None:
            monkeypatch.setenv(name, value)
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as client:
        for _ in range(2):
            response = client.get("/api/config")
            assert response.status_code == 200
            config = response.json()
            assert config["sec_configured"] == bool(sec and sec.strip() and "@" in sec)
            assert config["model_configured"] == bool(key and key.strip() and model and model.strip())
            assert config["model"] == (model.strip() or None if model else None)
            assert len(config["companies"]) == 5 and config["forecast_available"] is False
            assert config["fixture_cutoff"] == FIXTURE_CUTOFF.isoformat()
            for name in ("sec", "model"):
                assert config["connections"][name]["check"] == ConnectionCheck().model_dump(mode="json")
                assert config["connections"][name]["configured"] == config[f"{name}_configured"]


@pytest.mark.parametrize("base_url,provider", [(None, "OpenAI"), ("  ", "OpenAI"), ("https://user:private-api-key@private.invalid/v1?contact=private@example.invalid", "OpenAI-compatible")])
def test_config_hides_secrets_endpoint_and_contact(tmp_path, monkeypatch, base_url, provider):
    monkeypatch.setenv("SEC_USER_AGENT", "private@example.invalid")
    monkeypatch.setenv("OPENAI_API_KEY", "private-api-key")
    monkeypatch.setenv("RESEARCH_MODEL", "test-model")
    if base_url is not None:
        monkeypatch.setenv("OPENAI_BASE_URL", base_url)
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as client:
        config = client.get("/api/config").json()
        assert config["connections"]["sec"]["provider"] == "SEC"
        assert config["connections"]["sec"]["model"] is None
        assert config["connections"]["model"]["provider"] == provider
        assert config["connections"]["model"]["model"] == "test-model"
        encoded = json.dumps(config)
        assert all(secret not in encoded for secret in ("private-api-key", "private.invalid", "private@example.invalid", "OpenRouter"))
        assert config["connections"]["model"]["configured"] == (provider == "OpenAI")


@pytest.mark.parametrize("payload", [{"cik": 789019, "facts": {}}, {"cik": 789019, "facts": {"us-gaap": {"Revenues": {"units": {"USD": [{"start": "2024-01-01", "end": "2024-12-31", "val": 100, "accn": "annual", "filed": "2025-02-01", "form": "10-K"}]}}}}}])
def test_validated_sec_response_passes_even_without_eligible_facts(app, monkeypatch, payload):
    sec_transport(monkeypatch, httpx.Response(200, json=payload))
    result = run(app, mode="fresh", source_run_id=None, model_analysis=False)
    assert result.status == "completed"
    check = checked(app, "sec", "passed", result)
    assert "coverage is not guaranteed" in check.message
    assert app.connections()["model"].check.status == "not_tested"


@pytest.mark.parametrize("response", [httpx.Response(403), httpx.Response(200, content=b"invalid"), httpx.Response(200, json={"cik": 320193}), httpx.Response(200, json={"cik": 789019, "facts": {"us-gaap": {"Revenues": {"units": {"USD": {}}}}}})])
def test_sec_retrieval_and_validation_failures_are_observed(app, monkeypatch, response):
    sec_transport(monkeypatch, response)
    result = run(app, mode="fresh", source_run_id=None, model_analysis=False)
    assert result.status == "failed"
    checked(app, "sec", "failed", result)


@pytest.mark.parametrize("path", [("facts",), ("facts", "us-gaap"), ("facts", "us-gaap", "Revenues"), ("facts", "us-gaap", "Revenues", "units")])
def test_malformed_nested_sec_data_records_failure(app, monkeypatch, path):
    payload = {"cik": 789019}
    parent = payload
    for key in path[:-1]:
        parent[key] = {}
        parent = parent[key]
    parent[path[-1]] = []
    sec_transport(monkeypatch, httpx.Response(200, json=payload))
    result = run(app, mode="fresh", source_run_id=None, model_analysis=False)
    assert result.status == "failed"
    assert "invalid fact collection" in result.error
    checked(app, "sec", "failed", result)


@pytest.mark.parametrize("sec", [None, "  ", "Invalid contact"])
def test_missing_sec_configuration_does_not_claim_failure(app, monkeypatch, sec):
    if sec is not None:
        monkeypatch.setenv("SEC_USER_AGENT", sec)
    result = run(app, mode="fresh", source_run_id=None)
    assert result.status == "failed"
    assert app.connections()["sec"].check == ConnectionCheck()


def test_model_pass_requires_both_validated_responses_and_restart_clears(app, monkeypatch):
    calls = model_transport(monkeypatch)
    result = run(app)
    assert len(calls) == 2 and result.report.companies[0].review_status == "completed"
    checked(app, "model", "passed", result)
    assert app.connections()["sec"].check == ConnectionCheck()
    restarted = Application(app.store)
    try:
        assert all(info.check == ConnectionCheck() for info in restarted.connections().values())
    finally:
        restarted.close()


@pytest.mark.parametrize("failure", ["timeout", "malformed", "incomplete", "bad_refs", "numbers", "critic"])
def test_expected_model_failures_are_observed_with_safe_summaries(app, monkeypatch, failure):
    calls = model_transport(monkeypatch, failure)
    result = run(app)
    assert result.report.companies[0].review_status == "failed"
    assert len(calls) == (2 if failure == "critic" else 1)
    check = checked(app, "model", "failed", result)
    assert "private" not in check.model_dump_json()


@pytest.mark.parametrize("key,model", [(None, None), ("  ", "test-model"), ("test-key", "  ")])
def test_missing_model_configuration_does_not_claim_failure(app, monkeypatch, key, model):
    for name, value in (("OPENAI_API_KEY", key), ("RESEARCH_MODEL", model)):
        if value is not None:
            monkeypatch.setenv(name, value)
    result = run(app)
    assert result.report.companies[0].review_status == "unavailable"
    assert app.connections()["model"].check == ConnectionCheck()


def test_last_completed_attempt_survives_skips_replay_and_missing_configuration(app, monkeypatch):
    model_transport(monkeypatch)
    passed = run(app)
    first = checked(app, "model", "passed", passed)
    # Returning a snapshot never permits a caller to mutate application state.
    first.status = "failed"
    assert app.connections()["model"].check.status == "passed"
    model_transport(monkeypatch, "timeout")
    failed = run(app)
    last = checked(app, "model", "failed", failed)
    run(app, model_analysis=False)
    run(app, mode="replay")
    monkeypatch.delenv("OPENAI_API_KEY")
    run(app)
    assert app.connections()["model"].check == last
    assert app.connections()["sec"].check == ConnectionCheck()


def test_missing_evidence_skips_model_without_touching_its_check(app, monkeypatch):
    calls = model_transport(monkeypatch)
    sec_transport(monkeypatch, httpx.Response(200, json={"cik": 789019, "facts": {}}))
    result = run(app, mode="fresh", source_run_id=None)
    assert result.report.companies[0].review_status == "unavailable"
    assert not calls and app.connections()["model"].check == ConnectionCheck()


def test_budget_during_second_model_call_does_not_claim_provider_outcome(app, monkeypatch):
    calls = model_transport(monkeypatch)
    original = Budget.check
    def stop_before_critic(self):
        original(self)
        if self.calls == 1:
            raise DomainError("Budget exhausted", "budget_exhausted")
    monkeypatch.setattr(Budget, "check", stop_before_critic)
    result = run(app)
    assert result.status == "budget_exhausted" and len(calls) == 1
    assert app.connections()["model"].check == ConnectionCheck()


@pytest.mark.parametrize("connection", ["sec", "model"])
def test_unrelated_host_failures_do_not_claim_provider_outcome(app, monkeypatch, connection):
    if connection == "sec":
        def host_failure(*args):
            raise OSError("Local disk unavailable")
        monkeypatch.setattr("research_assistant.application.retrieve_company", host_failure)
        result = run(app, mode="fresh", source_run_id=None)
    else:
        model_transport(monkeypatch, "host")
        result = run(app)
    assert result.status == "failed"
    assert app.connections()[connection].check == ConnectionCheck()


def test_concurrent_config_snapshots_never_mix_check_fields(app):
    def update():
        for index in range(100):
            app._record_connection("sec", "passed" if index % 2 == 0 else "failed", f"run-{index}")
    def read():
        for _ in range(100):
            check = app.connections()["sec"].check
            if check.status != "not_tested":
                assert check.checked_at and check.message and check.run_id
                assert (int(check.run_id.split("-")[-1]) % 2 == 0) == (check.status == "passed")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(update), pool.submit(read), pool.submit(read)]
        for future in futures:
            future.result()
