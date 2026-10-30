import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from research_assistant.api import create_app
from research_assistant.application import Application, Budget, Critique, Draft, Interpretation, Objection, frozen_source_limitations
from research_assistant.contracts import CompanyReport, DomainError, RunRequest, Screen
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


def test_restart_marks_pending_model_analysis_interrupted(store):
    run_id, _ = store.accept(frozen(), "review-crashed")
    report = store.get("example-msft").report
    report.companies[0].review_status = "pending"
    store.update(run_id, status="running", report=report)
    store.recover()
    run = store.get(run_id)
    assert run.status == "interrupted"
    company = run.report.companies[0]
    assert company.review_status == "failed" and "restart" in company.review_error
    assert company.metrics == report.companies[0].metrics
    assert company.reviews == report.companies[0].reviews
    store.recover()
    assert store.get(run_id) == run


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
        assert run.status == "completed" and run.error is None
        company = run.report.companies[0]
        assert company.review_status == "unavailable"
        assert "not configured" in company.review_error
        assert company.metrics[2].value == Decimal("0.15")
        assert company.reviews == []  # New inference never borrows the fixture's recorded correction.
    finally:
        app.close()


@pytest.mark.parametrize("kind", ["research", "discovery"])
def test_model_opt_out_never_calls_a_configured_model(store, monkeypatch, kind):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("RESEARCH_MODEL", "test-model")
    def forbidden(*args, **kwargs):
        pytest.fail("Model analysis was not requested")
    monkeypatch.setattr("research_assistant.application.OpenAI", forbidden)
    changes = {"model_analysis": False}
    if kind == "discovery":
        changes.update(kind=kind, ticker=None, screen=Screen(), source_run_id="example-discovery")
    app = Application(store)
    try:
        run = wait_terminal(app, app.submit(frozen(**changes), "model-off").id)
        assert run.status == "completed" and run.error is None
        assert all(c.review_status == "not_requested" and c.review_error is None for c in run.report.companies)
        assert all(not c.reviews for c in run.report.companies)
        assert run.report.synthetic
        assert store.get(run.id).report == run.report
    finally:
        app.close()


def test_legacy_idempotency_keeps_old_intent_and_checks_new_choice(store):
    run_id, _ = store.accept(frozen(), "legacy-intent")
    old_request = frozen().model_dump(mode="json")
    old_request.pop("model_analysis", None)
    with store.connect() as db:
        db.execute("UPDATE runs SET request=? WHERE id=?", (json.dumps(old_request, sort_keys=True, separators=(",", ":")), run_id))
    assert store.accept(RunRequest.model_validate(old_request), "legacy-intent") == (run_id, False)
    with pytest.raises(DomainError, match="different inputs"):
        store.accept(frozen(model_analysis=False), "legacy-intent")


def test_source_request_cannot_change_cutoff(store):
    app = Application(store)
    try:
        with pytest.raises(DomainError, match="original"):
            app.submit(frozen(cutoff=datetime(2025, 3, 2, tzinfo=timezone.utc)), "bad-source-cutoff")
    finally:
        app.close()


def test_legacy_frozen_limitations_preserve_source_cautions_without_rewriting_replay(store):
    saved = store.get("example-msft")
    data = saved.report.companies[0].model_dump()
    data.pop("source_limitations")
    data["limitations"] = [
        "All figures and review steps in this saved example are synthetic teaching data, not investment research.",
        "Model review was not run. Set OPENAI_API_KEY and RESEARCH_MODEL on the server for fresh inference; these deterministic results are not agent-reviewed.",
        "No eligible evidence exists for model review.",
        "One structured interpretation/critic pass was run. Empty objections are not proof of correctness; narrative objections require adjudication. No full five-role agent evaluation is claimed.",
        "A source-specific caution that must survive.",
    ]
    legacy = CompanyReport.model_validate(data)
    assert legacy.source_limitations is None
    assert frozen_source_limitations(legacy) == [
        "All financial figures in this saved source are synthetic teaching data, not investment research.",
        "A source-specific caution that must survive.",
    ]
    assert legacy.limitations == data["limitations"]
    assert store.get(saved.id) == saved
    legacy.source_limitations = []
    assert frozen_source_limitations(legacy) == []


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


def test_sec_selects_latest_period_across_revenue_tags():
    payload = sec_payload()
    facts = payload["facts"]["us-gaap"]
    latest = facts["Revenues"]["units"]["USD"][0]
    older = {**latest, "start": "2023-01-01", "end": "2023-12-31", "filed": "2024-02-01", "accn": "older", "val": 50000000}
    facts["RevenueFromContractWithCustomerExcludingAssessedTax"] = {"units": {"USD": [older]}}
    revenue, income, tag = extract_annual(payload, "MSFT", FIXTURE_CUTOFF)
    assert revenue.accn == income.accn == "annual"
    assert income.val / revenue.val == Decimal("0.15")
    assert tag == "Revenues"


def test_sec_reconciles_duplicate_revenue_tags_and_rejects_conflicts():
    payload = sec_payload()
    facts = payload["facts"]["us-gaap"]
    annual = facts["Revenues"]["units"]["USD"][0]
    duplicate = {**annual}
    facts["RevenueFromContractWithCustomerExcludingAssessedTax"] = {"units": {"USD": [duplicate]}}
    revenue, _, tag = extract_annual(payload, "MSFT", FIXTURE_CUTOFF)
    assert revenue.val == Decimal("100000000")
    assert tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    duplicate["val"] = 7
    with pytest.raises(DomainError, match="Conflicting revenue"):
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


@pytest.mark.parametrize("model_analysis", [False, True])
def test_sec_boundary_with_mocked_transport(store, monkeypatch, model_analysis):
    import httpx
    from research_assistant import research
    monkeypatch.setenv("SEC_USER_AGENT", "Research tests contact@example.invalid")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    real_client = httpx.Client
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=sec_payload()))
    monkeypatch.setattr(research.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
    app = Application(store)
    try:
        request = RunRequest(mode="fresh", ticker="MSFT", cutoff=FIXTURE_CUTOFF, model_analysis=model_analysis)
        result = wait_terminal(app, app.submit(request, "recorded-sec").id)
        assert result.status == "completed" and result.error is None
        assert not result.report.synthetic
        assert result.report.companies[0].review_status == ("unavailable" if model_analysis else "not_requested")
        assert result.report.companies[0].metrics[2].value == Decimal("0.15")
        evidence = store.all_evidence(result.id)[0]
        assert json.loads((store.root / "snapshots" / f"{evidence.snapshot_hash}.json").read_bytes())["cik"] == 789019
    finally:
        app.close()


def test_structured_model_review_checks_ids_and_preserves_objections(store, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_MODEL", raising=False)
    app = Application(store)
    try:
        unreviewed = wait_terminal(app, app.submit(frozen(), "before-model-setup").id)
        assert unreviewed.status == "completed"
        assert unreviewed.report.companies[0].review_status == "unavailable"
    finally:
        app.close()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("RESEARCH_MODEL", "test-model")
    results = iter([Draft(interpretations=[Interpretation(statement="Margin alone does not establish cash generation.", evidence_ids=["fixture-MSFT-annual"])]), Critique(objections=[Objection(claim_id="MSFT-margin", explanation="Confirm the annual period alignment.", evidence_ids=["fixture-MSFT-annual"], requested_check="operating_margin")])])
    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = self
            self.with_raw_response = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def parse(self, **kwargs):
            return SimpleNamespace(http_response=SimpleNamespace(json=lambda: {"usage": {"total_tokens": 50}}), parse=lambda: SimpleNamespace(status="completed", output_parsed=next(results)))
    monkeypatch.setattr("research_assistant.application.OpenAI", FakeClient)
    app = Application(store)
    try:
        result = wait_terminal(app, app.submit(frozen(source_run_id=unreviewed.id), "model-success").id)
        assert result.status == "completed"
        company = result.report.companies[0]
        assert company.review_status == "completed" and company.review_error is None
        assert company.reviews[0].disposition == "unresolved"
        assert "15000000 / 100000000" in company.reviews[0].check
        assert company.claims[0].status == "unresolved"
        assert company.forecast.probability is None
        assert not any("Model review was not run" in line for line in company.limitations)
        assert company.source_limitations == unreviewed.report.companies[0].source_limitations
        assert store.get(unreviewed.id).report == unreviewed.report
    finally:
        app.close()


@pytest.mark.parametrize("failure", ["timeout", "incomplete", "bad_evidence", "bad_critic"])
def test_model_failure_is_separate_and_preserves_financial_results(store, monkeypatch, failure):
    from types import SimpleNamespace
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("RESEARCH_MODEL", "test-model")
    calls = []
    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs == {"api_key": "test-only-not-a-real-key", "base_url": "https://api.openai.com/v1", "timeout": 45, "max_retries": 0}
            self.responses = self
            self.with_raw_response = self
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def parse(self, **kwargs):
            calls.append(kwargs)
            if failure == "timeout":
                raise TimeoutError("No response")
            if failure == "incomplete":
                return SimpleNamespace(http_response=SimpleNamespace(json=lambda: {}), parse=lambda: SimpleNamespace(status="incomplete", output_parsed=None))
            if len(calls) == 1:
                result = Draft(interpretations=[Interpretation(statement="Margin alone does not establish cash generation.", evidence_ids=["unknown" if failure == "bad_evidence" else "fixture-MSFT-annual"])])
            else:
                result = Critique(objections=[Objection(claim_id="unknown", explanation="Check source support.", evidence_ids=["fixture-MSFT-annual"], requested_check="source_support")])
            return SimpleNamespace(http_response=SimpleNamespace(json=lambda: {"usage": {"total_tokens": 50}}), parse=lambda: SimpleNamespace(status="completed", output_parsed=result))
    monkeypatch.setattr("research_assistant.application.OpenAI", FakeClient)
    app = Application(store)
    try:
        run = wait_terminal(app, app.submit(frozen(), "model-failed").id)
        assert run.status == "completed" and run.error is None
        company = run.report.companies[0]
        assert company.review_status == "failed" and company.review_error
        assert company.metrics[2].value == Decimal("0.15")
        assert company.reviews == []
        assert store.all_evidence(run.id) == store.all_evidence("example-msft")
        assert store.get(run.id).report == run.report
        assert len(calls) == (2 if failure == "bad_critic" else 1)
        if failure == "bad_critic":
            assert company.claims[-1].kind == "interpretation"
    finally:
        app.close()


def test_budget_during_model_analysis_preserves_report_and_failed_review_status(store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-not-a-real-key")
    monkeypatch.setenv("RESEARCH_MODEL", "test-model")
    def exhausted(*args):
        raise DomainError("Model budget exhausted", "budget_exhausted")
    monkeypatch.setattr(Application, "review_company", exhausted)
    app = Application(store)
    try:
        run = wait_terminal(app, app.submit(frozen(), "review-budget").id)
        assert run.status == "budget_exhausted"
        assert run.report.companies[0].review_status == "failed"
        assert run.report.companies[0].review_error == "Model budget exhausted"
        assert run.report.companies[0].metrics[2].value == Decimal("0.15")
    finally:
        app.close()


def test_missing_model_does_not_abort_discovery(store, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_MODEL", raising=False)
    app = Application(store)
    try:
        request = frozen(kind="discovery", ticker=None, screen=Screen(), source_run_id="example-discovery")
        run = wait_terminal(app, app.submit(request, "discovery-model-missing").id)
        assert run.status == "completed" and len(run.report.companies) == 5
        selected = {c.ticker for c in run.report.candidates if c.selected}
        assert selected == {"AAPL", "GOOGL", "MSFT"}
        for company in run.report.companies:
            assert company.review_status == ("unavailable" if company.ticker in selected else "not_requested")
    finally:
        app.close()


def test_legacy_report_and_replay_do_not_invent_review_status(store, monkeypatch):
    saved = store.get("example-msft")
    report_data = saved.report.model_dump(mode="json")
    for company in report_data["companies"]:
        company.pop("review_status")
        company.pop("review_error")
    original_bytes = json.dumps(report_data)
    with store.connect() as db:
        db.execute("UPDATE runs SET report=? WHERE id=?", (original_bytes, saved.id))
    assert store.get(saved.id).report.companies[0].review_status == "not_recorded"
    def forbidden(*args, **kwargs):
        pytest.fail("Replay must not call external services")
    monkeypatch.setattr("research_assistant.application.OpenAI", forbidden)
    monkeypatch.setattr("research_assistant.application.retrieve_company", forbidden)
    app = Application(store)
    try:
        run = wait_terminal(app, app.submit(frozen(mode="replay", model_analysis=True), "legacy-replay").id)
        assert run.report == store.get(saved.id).report
        with store.connect() as db:
            assert db.execute("SELECT report FROM runs WHERE id=?", (saved.id,)).fetchone()[0] == original_bytes
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
