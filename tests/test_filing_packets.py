"""C1 packet boundaries: synthetic transports and preserved public filing bytes only."""
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from research_assistant.contracts import DomainError
from research_assistant.filings import Document, fetch_source, retrieve_packet
from research_assistant.research import SecFact
from research_assistant.store import Store

PACKET = Path(__file__).resolve().parents[1] / "verification/packets/msft-fy2024/20261029T182734Z"
# The packet holds 48 MB of real SEC files and is git-ignored, so fresh clones and CI skip these tests.
needs_packet = pytest.mark.skipif(not PACKET.is_dir(), reason="needs the local SEC packet in verification/packets/")
CUTOFF = datetime(2025, 3, 1, tzinfo=timezone.utc)


def annual():
    return SecFact(start="2023-07-01", end="2024-06-30", val="245122000000", accn="0000950170-24-087843", filed="2024-07-30", form="10-K")


@needs_packet
def test_real_packet_retrieval_preserves_bytes(tmp_path):
    def handler(request):
        name = "sec-index.html" if request.url.path.endswith("-index.htm") else "sec-filing.html"
        return httpx.Response(200, content=(PACKET / "raw" / name).read_bytes())
    store = Store(tmp_path)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        packet, doc, url, at = retrieve_packet(store, "MSFT", annual(), CUTOFF, client, "Test contact@example.invalid")
    assert packet.accession == annual().accn and len(packet.documents) == 2
    assert url.endswith("/msft-20240630.htm")
    assert any(n.text() == "245,122" for n in doc.root.nodes("ix:nonfraction"))
    assert store.snapshot_bytes(packet.documents[1].snapshot_hash) == (PACKET / "raw/sec-filing.html").read_bytes()


@needs_packet
@pytest.mark.parametrize("mutation,code", [("issuer", "issuer_mismatch"), ("accession", "issuer_mismatch"), ("date", "source_format"), ("external", "source_format")])
def test_index_identity_and_link_boundary(tmp_path, mutation, code):
    raw = (PACKET / "raw/sec-index.html").read_bytes()
    if mutation == "issuer":
        raw = raw.replace(b"0000789019", b"0000320193")
    elif mutation == "accession":
        raw = raw.replace(annual().accn.encode(), b"0000950170-24-000000")
    elif mutation == "date":
        raw = raw.replace(b"2024-07-30", b"2025-07-30")
    else:
        raw = raw.replace(b'"/ix?doc=/Archives/edgar/data/789019/000095017024087843/msft-20240630.htm"', b'"https://attacker.invalid/file.htm"')
    assert raw != (PACKET / "raw/sec-index.html").read_bytes()
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=raw))) as client:
        with pytest.raises(DomainError) as caught:
            retrieve_packet(Store(tmp_path), "MSFT", annual(), CUTOFF, client, "Test contact@example.invalid")
    assert caught.value.code == code


@needs_packet
def test_packet_cutoff_rejected_before_filing_download(tmp_path):
    calls = []
    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, content=(PACKET / "raw/sec-index.html").read_bytes())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DomainError, match="cutoff"):
            retrieve_packet(Store(tmp_path), "MSFT", annual(), datetime(2024, 7, 30, 22, tzinfo=timezone.utc), client, "Test contact@example.invalid")
    assert len(calls) == 1


def test_source_failure_oversize_and_hash_integrity(tmp_path, monkeypatch):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403))) as client:
        with pytest.raises(DomainError) as error:
            fetch_source(client, "https://www.sec.gov/test", "Test contact@example.invalid")
    assert error.value.code == "retrieval_failed"
    monkeypatch.setattr("research_assistant.filings.MAX_SOURCE_BYTES", 3)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"four"))) as client:
        with pytest.raises(DomainError) as error:
            fetch_source(client, "https://www.sec.gov/test", "Test contact@example.invalid")
    assert error.value.code == "source_limit"
    store = Store(tmp_path)
    digest = store.snapshot(b"original")
    (store.root / "snapshots" / f"{digest}.json").write_bytes(b"changed")
    with pytest.raises(DomainError, match="integrity"):
        store.snapshot_bytes(digest)
    with pytest.raises(DomainError, match="integrity"):
        store.snapshot(b"original")


def test_sec_requests_are_paced(monkeypatch):
    pauses = []
    monkeypatch.setattr("research_assistant.filings.time.sleep", pauses.append)
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"source"))) as client:
        for _ in range(3):
            fetch_source(client, "https://www.sec.gov/test", "Test contact@example.invalid")
    assert pauses == [0.11, 0.11, 0.11]


@needs_packet
def test_real_research_frozen_replay_and_immutable_records(tmp_path, monkeypatch):
    from decimal import Decimal
    import time
    from research_assistant import research
    from research_assistant.application import Application
    from research_assistant.contracts import Report, RunRequest
    calls = []
    def handler(request):
        calls.append(str(request.url))
        name = "companyfacts.json" if "companyfacts" in request.url.path else "sec-index.html" if request.url.path.endswith("-index.htm") else "sec-filing.html"
        return httpx.Response(200, content=(PACKET / "raw" / name).read_bytes())
    real_client = httpx.Client
    monkeypatch.setenv("SEC_USER_AGENT", "Test contact@example.invalid")
    monkeypatch.setattr(research.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    store = Store(tmp_path)
    app = Application(store)
    def finish(request, key):
        run = app.submit(request, key)
        for _ in range(1500):
            run = store.get(run.id)
            if run.status not in {"queued", "running"}:
                assert run.status == "completed", run.error
                return run
            time.sleep(.01)
        pytest.fail("Run did not finish")
    try:
        fresh = finish(RunRequest(mode="fresh", ticker="MSFT", cutoff=CUTOFF, model_analysis=False), "original-real-packet")
        company = fresh.report.companies[0]
        assert len(calls) == 3 and len(company.facts) == 2 and len(company.calculations) == 1
        assert company.metrics[2].value == Decimal("0.4464429957327371676144940071")
        assert all(store.fact(f.id) == f for f in company.facts)
        assert store.calculation(company.calculations[0].id) == company.calculations[0]
        sources = store.all_evidence(fresh.id)
        original = next(e for e in sources if e.packet)
        assert original.source_kind == "filing_table" and len(original.packet.documents) == 3
        source_bytes = {d.snapshot_hash: store.snapshot_bytes(d.snapshot_hash) for d in original.packet.documents}
        def forbidden(**kwargs):
            pytest.fail("Frozen/replay made a network call")
        monkeypatch.setattr(research.httpx, "Client", forbidden)
        for mode in ("frozen", "replay"):
            saved = finish(RunRequest(mode=mode, ticker="MSFT", cutoff=CUTOFF, source_run_id=fresh.id, model_analysis=False), "original-real-" + mode)
            copied = saved.report.companies[0]
            assert copied.facts == company.facts and copied.calculations == company.calculations
            assert store.all_evidence(saved.id) == sources
            assert all(store.snapshot_bytes(key) == value for key, value in source_bytes.items())
        for field in ("fact", "calculation"):
            altered = company.model_copy(deep=True)
            if field == "fact":
                altered.facts[0] = altered.facts[0].model_copy(update={"normalized_value": Decimal("1")})
            else:
                altered.calculations[0] = altered.calculations[0].model_copy(update={"result": Decimal("1")})
            with pytest.raises(DomainError):
                store.update(fresh.id, report=Report(title="forged", synthetic=False, companies=[altered]))
            assert store.get(fresh.id).report == fresh.report
        with store.connect() as db:
            row = db.execute("SELECT report FROM runs WHERE id=?", (fresh.id,)).fetchone()[0]
        # Reopening the new schema must not rewrite a completed report.
        reopened = Store(tmp_path)
        assert reopened.get(fresh.id).report == fresh.report
        with reopened.connect() as db:
            assert db.execute("SELECT report FROM runs WHERE id=?", (fresh.id,)).fetchone()[0] == row
    finally:
        app.close()


def test_source_download_is_evidence_scoped_and_byte_stable(tmp_path):
    from fastapi.testclient import TestClient
    from research_assistant.api import create_app
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1:8000") as client:
        store = client.app.state.store
        evidence = store.all_evidence("example-msft")[0]
        base = f"/api/runs/example-msft/evidence/{evidence.id}/sources/"
        result = client.get(base + evidence.snapshot_hash)
        assert result.status_code == 200 and result.content == store.snapshot_bytes(evidence.snapshot_hash)
        assert result.headers["content-type"] == "application/octet-stream"
        assert result.headers["content-disposition"].startswith("attachment;")
        other = store.all_evidence("example-aapl")[0]
        assert client.get(base + other.snapshot_hash).status_code == 404


@needs_packet
def test_original_document_wrong_period_or_amendment_rejected(tmp_path):
    for field in ("dei:DocumentPeriodEndDate", "dei:AmendmentFlag"):
        filing = (PACKET / "raw/sec-filing.html").read_bytes()
        doc = Document(filing)
        node = next(n for n in doc.root.nodes("ix:nonnumeric") if n.attrs.get("name") == field)
        old = doc.fragment(node)[0]
        new = old.replace(b"2024", b"2025") if field.endswith("EndDate") else old.replace(b"false", b"true")
        changed = filing.replace(old, new)
        assert filing != changed
        def handler(request, changed=changed):
            return httpx.Response(200, content=(PACKET / "raw/sec-index.html").read_bytes() if request.url.path.endswith("-index.htm") else changed)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(DomainError, match="period/amendment"):
                retrieve_packet(Store(tmp_path), "MSFT", annual(), CUTOFF, client, "Test contact@example.invalid")


@pytest.mark.parametrize("revenue,income,failure", [(0, 15, "nonpositive_revenue"), (-1, 15, "nonpositive_revenue"), (100, None, "missing_input")])
def test_calculation_failures_are_saved_and_reproducible(tmp_path, monkeypatch, revenue, income, failure):
    from research_assistant import research
    from research_assistant.contracts import Report, RunRequest
    from research_assistant.financials import operating_margin
    from sec_fixture import source_response
    from test_system import sec_payload
    payload = sec_payload()
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]["val"] = abs(revenue)
    if income is None:
        payload["facts"]["us-gaap"]["OperatingIncomeLoss"]["units"]["USD"] = []
    client_class = httpx.Client
    def handler(request):
        response = source_response(request, payload)
        if revenue < 0 and str(request.url).endswith("annual.htm"):
            return httpx.Response(200, content=response.content.replace(b'id="Revenues"', b'id="Revenues" sign="-"'))
        if revenue < 0 and "companyfacts" in request.url.path:
            altered = response.json()
            altered["facts"]["us-gaap"]["Revenues"]["units"]["USD"][0]["val"] = revenue
            return httpx.Response(200, json=altered)
        return response
    monkeypatch.setenv("SEC_USER_AGENT", "Test contact@example.invalid")
    monkeypatch.setattr(research.httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(handler), **kw))
    store = Store(tmp_path)
    run_id, _ = store.accept(RunRequest(mode="fresh", ticker="MSFT", cutoff=CUTOFF, model_analysis=False), "typed-failure")
    company = research.retrieve_company(store, run_id, "MSFT", CUTOFF)
    store.update(run_id, report=Report(title="Failure case", synthetic=False, companies=[company]), status="completed")
    calculation = company.calculations[0]
    assert calculation.result is None and calculation.failure == failure
    assert store.calculation(calculation.id) == calculation
    revenue_fact = next((f for f in company.facts if f.concept == "us-gaap:Revenues"), None)
    income_fact = next((f for f in company.facts if f.concept == "us-gaap:OperatingIncomeLoss"), None)
    assert operating_margin(revenue_fact, income_fact) == calculation
