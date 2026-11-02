"""Synthetic teaching fixture. Every value and correction is deliberately invented."""

import json
from datetime import datetime, timezone
from decimal import Decimal

from .contracts import Evidence, Report, Review, RunRequest, Screen, UNIVERSE
from .research import company_report, metrics
from .screening import screen_companies

FIXTURE_CUTOFF = datetime(2025, 3, 1, 23, 59, tzinfo=timezone.utc)
FIXTURE_VALUES = {"MSFT": (100, 15), "AAPL": (120, 30), "AMZN": (200, 12), "GOOGL": (150, 40), "NVDA": (80, None)}


def seed(store):
    reports = []
    for ticker, (revenue, income) in FIXTURE_VALUES.items():
        run_id = f"example-{ticker.lower()}"
        request = RunRequest(mode="replay", ticker=ticker, cutoff=FIXTURE_CUTOFF, source_run_id=run_id)
        evidence_id = f"fixture-{ticker}-annual"
        excerpt = f"SYNTHETIC TEACHING DATA — not an actual {UNIVERSE[ticker]['name']} filing.\nAnnual period: 2024-01-01 to 2024-12-31\nRevenue: USD {revenue},000,000\nOperating income: {'unavailable' if income is None else f'USD {income},000,000'}\nFor the MSFT correction exercise only: quarterly operating income is USD 3,000,000 for 2024-10-01 to 2024-12-31. It cannot be divided by annual revenue."
        digest = store.snapshot(json.dumps({"synthetic": True, "ticker": ticker, "excerpt": excerpt}).encode())
        evidence = Evidence(id=evidence_id, ticker=ticker, title=f"{ticker} · synthetic annual statement", excerpt=excerpt, source_url=None, available_at=datetime(2025, 2, 1, tzinfo=timezone.utc), retrieved_at=FIXTURE_CUTOFF, period="2024-01-01 – 2024-12-31", locator="Teaching fixture / income statement / annual USD values", snapshot_hash=digest, synthetic=True)
        values = metrics(Decimal(revenue) * 1_000_000, Decimal(income) * 1_000_000 if income is not None else None, evidence.period, [evidence_id])
        company = company_report(ticker, values, ["All financial figures in this saved source are synthetic teaching data, not investment research.", "Free cash flow, news and historical prices are absent from this evidence packet."])
        if ticker == "MSFT":
            company.claims[0].version = 2
            company.claims[0].status = "corrected"
            company.reviews = [Review(claim_id="MSFT-margin", original="Annual operating margin is 3.0%.", objection="The draft divides quarterly operating income by annual revenue. The periods do not match.", check="Rejected USD 3,000,000 quarterly income. Matched annual operating income of USD 15,000,000 to annual revenue of USD 100,000,000; recomputed 15,000,000 / 100,000,000 = 0.15.", revised=company.claims[0].statement, disposition="corrected", evidence_ids=[evidence_id])]
            company.summary = "A period mismatch changed the result. The saved teaching example corrects annual operating margin from 3.0% to 15.0%, with the original inputs and review preserved."
        report = Report(title=f"{company.company} research", synthetic=True, companies=[company])
        reports.append(company)
        with store.connect() as db:
            exists = db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone()
            if exists:
                continue
            db.execute("INSERT INTO runs VALUES (?,?,?,'completed',?,?,'Saved teaching example',?,NULL,1)", (run_id, run_id, store.canonical(request), FIXTURE_CUTOFF.isoformat(), FIXTURE_CUTOFF.isoformat(), report.model_dump_json()))
        store.add_evidence(run_id, evidence)
        store.action(run_id, "Fixture", "Loaded synthetic annual statement; no external retrieval or model call.")
        store.action(run_id, "Calculation", "Checked annual periods and calculated operating margin." if income is not None else "Missing operating income; calculation abstained.")
        if ticker == "MSFT":
            store.action(run_id, "Recorded review", "Teaching correction: rejected mixed periods and recomputed annual margin.")
    run_id = "example-discovery"
    request = RunRequest(kind="discovery", mode="replay", cutoff=FIXTURE_CUTOFF, source_run_id=run_id, screen=Screen())
    report = Report(title="Five-company discovery", synthetic=True, companies=reports, candidates=screen_companies(reports, request.screen), ranking="Alphabetical among eligible companies. Forecast ranking is unavailable.", limitations=["Fixed five-company teaching universe, not a market-wide search. All financial values are synthetic."])
    with store.connect() as db:
        exists = db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone()
        if exists:
            return
        db.execute("INSERT INTO runs VALUES (?,?,?,'completed',?,?,'Saved teaching screen',?,NULL,1)", (run_id, run_id, store.canonical(request), FIXTURE_CUTOFF.isoformat(), FIXTURE_CUTOFF.isoformat(), report.model_dump_json()))
    for ticker in UNIVERSE:
        for evidence in store.all_evidence(f"example-{ticker.lower()}"):
            store.add_evidence(run_id, evidence)
    store.action(run_id, "Screen", "Screened five synthetic companies. Preserved pass, fail and unknown outcomes.")
