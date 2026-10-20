import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from research_assistant.api import create_app
from research_assistant.application import Application, Budget, Critique, Draft, Interpretation, Objection
from research_assistant.contracts import DomainError, RunRequest, Screen
from research_assistant.fixtures import FIXTURE_CUTOFF, seed
from research_assistant.research import conservative_availability, extract_annual
from research_assistant.screening import screen_companies
from research_assistant.store import Store


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path)
    seed(result)
    return result


def frozen(**changes):
    return RunRequest(**{"mode": "frozen", "ticker": "MSFT", "cutoff": FIXTURE_CUTOFF, "source_run_id": "example-msft", **changes})


def wait_terminal(app, run_id):
    for _ in range(200):
        run = app.store.get(run_id)
        if run.status not in ("queued", "running"):
            return run
        time.sleep(.01)
    pytest.fail("Run did not terminate")


def test_fixture_has_traceable_calculation_and_missing_forecast(store):
    run = store.get("example-msft")
    company = run.report.companies[0]
    assert company.metrics[2].value == Decimal("0.15")
    assert company.claims[0].version == 2
    assert company.reviews[0].original == "Annual operating margin is 3.0%."
    assert company.forecast.probability is None
    for claim in company.claims:
        for evidence_id in claim.evidence_ids:
            evidence = store.evidence(run.id, evidence_id)
            assert evidence.synthetic
            assert evidence.available_at <= run.request.cutoff
            assert (store.root / "snapshots" / f"{evidence.snapshot_hash}.json").is_file()


def test_concurrent_idempotent_submission_is_one_run(store):
    request = frozen()
    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(lambda _: store.accept(request, "same-intent"), range(8)))
    assert len({r[0] for r in accepted}) == 1
    assert sum(r[1] for r in accepted) == 1
    with pytest.raises(DomainError, match="different inputs"):
        store.accept(frozen(ticker="AAPL"), "same-intent")
    with pytest.raises(DomainError, match="already active"):
        store.accept(request, "different-intent")


def test_restart_preserves_partial_and_never_retries(store):
    run_id, _ = store.accept(frozen(), "crashed-intent")
    store.update(run_id, status="running", report=store.get("example-msft").report)
    store.action(run_id, "Filings", "Saved original evidence")
    store.recover()
    result = store.get(run_id)
    assert result.status == "interrupted"
    assert result.report and len(result.actions) == 1
    assert store.accept(frozen(), "crashed-intent") == (run_id, False)


def test_unknown_never_passes_and_sort_does_not_invent_forecast(store):
    companies = store.get("example-discovery").report.companies
    candidates = screen_companies(companies, Screen())
    assert [c.ticker for c in candidates if c.selected] == ["AAPL", "GOOGL", "MSFT"]
    assert next(c for c in candidates if c.ticker == "NVDA").eligibility == "unknown"
    assert next(c for c in candidates if c.ticker == "AMZN").eligibility == "fail"
    assert not any(c.selected for c in screen_companies(companies, Screen(min_operating_margin=Decimal("1"))))


def test_evidence_is_immutable_scoped_and_cutoff_checked(store):
    evidence = store.evidence("example-msft", "fixture-MSFT-annual")
    with pytest.raises(DomainError, match="unavailable"):
        store.evidence("example-aapl", evidence.id)
    with pytest.raises(DomainError, match="immutable"):
        store.add_evidence("example-msft", evidence.model_copy(update={"excerpt": "Changed"}))
    with pytest.raises(DomainError, match="later"):
        store.add_evidence("example-msft", evidence.model_copy(update={"available_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}))


@pytest.mark.parametrize("changes", [{"cutoff": "2025-01-01T00:00:00"}, {"ticker": "UNKNOWN"}, {"mode": "fresh"}, {"screen": {"min_operating_margin": "NaN"}}, {"cutoff": "2099-01-01T00:00:00Z"}])
def test_request_boundaries(changes):
    with pytest.raises(ValidationError):
        frozen(**changes)


def test_replay_and_repeated_reads_have_no_model_or_retrieval(store, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Replay called an external function")
    monkeypatch.setattr("research_assistant.application.retrieve_company", forbidden)
    monkeypatch.setattr("research_assistant.application.OpenAI", forbidden)
    app = Application(store)
    try:
        result = app.submit(frozen(mode="replay"), "replay-intent")
        result = wait_terminal(app, result.id)
        assert result.status == "completed"
        assert result.report == store.get("example-msft").report
        assert app.submit(frozen(mode="replay"), "replay-intent").id == result.id
        assert store.get(result.id).report == result.report
        assert store.evidence(result.id, "fixture-MSFT-annual").synthetic
    finally:
        app.close()


def test_missing_model_preserves_frozen_results(store, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_MODEL", raising=False)
    app = Application(store)
    try:
        run = wait_terminal(app, app.submit(frozen(), "missing-model").id)
        assert run.status == "failed" and "model review is unavailable" in run.error
        assert run.report.companies[0].metrics[2].value == Decimal("0.15")
        assert run.report.companies[0].reviews == []  # New inference never borrows the fixture's recorded correction.
    finally:
        app.close()


def test_source_request_cannot_change_cutoff(store):
    app = Application(store)
    try:
        with pytest.raises(DomainError, match="original"):
            app.submit(frozen(cutoff=datetime(2025, 3, 2, tzinfo=timezone.utc)), "bad-source-cutoff")
    finally:
        app.close()


def sec_payload():
    annual = {"start": "2024-01-01", "end": "2024-12-31", "val": 100000000, "accn": "annual", "filed": "2025-02-01", "form": "10-K"}
    quarterly = {**annual, "start": "2024-10-01", "val": 3000000}
    income = {**annual, "val": 15000000}
    return {"cik": 789019, "facts": {"us-gaap": {"Revenues": {"units": {"USD": [annual]}}, "OperatingIncomeLoss": {"units": {"USD": [quarterly, income]}}}}}


def test_sec_rejects_mismatched_period_future_restatement_and_issuer():
    payload = sec_payload()
    rev, income, _ = extract_annual(payload, "MSFT", FIXTURE_CUTOFF)
    assert income.val / rev.val == Decimal("0.15")
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append({"start": "2024-01-01", "end": "2024-12-31", "val": 999, "accn": "future", "filed": "2026-01-01", "form": "10-K/A"})
    assert extract_annual(payload, "MSFT", FIXTURE_CUTOFF)[0] == rev
    assert extract_annual(payload, "MSFT", datetime(2025, 2, 1, 23, 59, tzinfo=timezone.utc))[0] is None
    with pytest.raises(DomainError, match="issuer"):
        extract_annual(payload, "AAPL", FIXTURE_CUTOFF)


def test_sec_ambiguous_values_and_missing_income():
    payload = sec_payload()
    income_units = payload["facts"]["us-gaap"]["OperatingIncomeLoss"]["units"]["USD"]
    income_units.pop()
    assert extract_annual(payload, "MSFT", FIXTURE_CUTOFF)[1] is None
    revenue_units = payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"]
    revenue_units.append({**revenue_units[0], "val": 7})
    with pytest.raises(DomainError, match="Conflicting"):
        extract_annual(payload, "MSFT", FIXTURE_CUTOFF)


def test_filing_date_availability_uses_eastern_calendar_including_dst():
    from datetime import date
    assert conservative_availability(date(2025, 2, 1)) == datetime(2025, 2, 2, 5, tzinfo=timezone.utc)
    assert conservative_availability(date(2025, 7, 1)) == datetime(2025, 7, 2, 4, tzinfo=timezone.utc)
    assert extract_annual(sec_payload(), "MSFT", datetime(2025, 2, 2, 2, tzinfo=timezone.utc))[0] is None


def test_budget_termination_preserves_unresolved_results(store, monkeypatch):
    def exhausted(self):
        raise DomainError("Budget exhausted", "budget_exhausted")
    monkeypatch.setattr(Budget, "check", exhausted)
    app = Application(store)
    try:
        run = wait_terminal(app, app.submit(frozen(), "budget-intent").id)
        assert run.status == "budget_exhausted"
        assert run.report is None
    finally:
        app.close()


def test_live_sec_boundary_with_recorded_transport(store, monkeypatch):
    import httpx
    from research_assistant import research
    monkeypatch.setenv("SEC_USER_AGENT", "Research tests contact@example.invalid")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=sec_payload()))
    monkeypatch.setattr(research.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
    app = Application(store)
    try:
        request = RunRequest(mode="fresh", ticker="MSFT", cutoff=FIXTURE_CUTOFF)
        result = wait_terminal(app, app.submit(request, "recorded-sec").id)
        assert result.status == "failed"  # Model not configured, valid partial financial report retained.
        assert result.report.companies[0].metrics[2].value == Decimal("0.15")
        evidence = store.all_evidence(result.id)[0]
        assert json.loads((store.root / "snapshots" / f"{evidence.snapshot_hash}.json").read_bytes())["cik"] == 789019
    finally:
        app.close()


def test_structured_model_review_checks_ids_and_preserves_objections(store, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("RESEARCH_MODEL", "test-model")
    results = iter([Draft(interpretations=[Interpretation(statement="Margin alone does not establish cash generation.", evidence_ids=["fixture-MSFT-annual"])]), Critique(objections=[Objection(claim_id="MSFT-margin", explanation="Confirm the annual period alignment.", evidence_ids=["fixture-MSFT-annual"], requested_check="operating_margin")])])
    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def parse(self, **kwargs):
            return SimpleNamespace(status="completed", output_parsed=next(results), usage=SimpleNamespace(total_tokens=50))
    monkeypatch.setattr("research_assistant.application.OpenAI", FakeClient)
    app = Application(store)
    try:
        result = wait_terminal(app, app.submit(frozen(), "model-success").id)
        assert result.status == "completed"
        company = result.report.companies[0]
        assert company.reviews[0].disposition == "unresolved"
        assert "15000000 / 100000000" in company.reviews[0].check
        assert company.claims[0].status == "unresolved"
        assert company.forecast.probability is None
    finally:
        app.close()


def test_api_security_validation_and_evidence_scope(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as client:
        response = client.get("/api/runs/example-msft")
        assert response.status_code == 200
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert client.get("/api/runs/example-aapl/evidence/fixture-MSFT-annual").status_code == 404
        assert client.get("/api/runs", headers={"Host": "attacker.test"}).status_code == 400
        assert client.post("/api/runs", headers={"Origin": "https://attacker.test"}, json={}).status_code == 403
        assert client.post("/api/runs", content="x").status_code == 415
        assert client.post("/api/runs", json={}).status_code == 422
        assert client.get("/api/runs?limit=2").json()["total"] == 6
        assert len(client.get("/api/runs?limit=2").json()["items"]) == 2
        config = client.get("/api/config").json()
        assert "OPENAI_API_KEY" not in str(config)
        body = frozen(mode="replay").model_dump(mode="json")
        first = client.post("/api/runs", json=body, headers={"Idempotency-Key": "api-replay-intent"})
        second = client.post("/api/runs", json=body, headers={"Idempotency-Key": "api-replay-intent"})
        assert first.status_code == second.status_code == 202
        assert first.json()["id"] == second.json()["id"]


def test_second_server_cannot_interrupt_first(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000"):
        with pytest.raises(RuntimeError, match="Another research server"):
            with TestClient(create_app(tmp_path), base_url="http://localhost:8000"):
                pass
