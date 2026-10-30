"""Mutable organization must never alter saved research or submission identity."""

import pytest
from fastapi.testclient import TestClient

from research_assistant.api import create_app
from research_assistant.application import Application
from research_assistant.contracts import DomainError, RunMetadataPatch, RunRequest
from research_assistant.fixtures import FIXTURE_CUTOFF, seed
from research_assistant.store import Store


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path)
    seed(result)
    return result


def test_metadata_preserves_original_research_and_survives_restart(store):
    original = store.get("example-msft")
    evidence = store.all_evidence(original.id)
    with store.connect() as db:
        raw = tuple(db.execute("SELECT request,report,updated_at FROM runs WHERE id=?", (original.id,)).fetchone())
    changed = store.set_metadata(original.id, RunMetadataPatch(label="  Review Microsoft  ", archived=True))
    assert changed.label == "Review Microsoft" and changed.archived
    assert changed.model_dump(exclude={"label", "archived"}) == original.model_dump(exclude={"label", "archived"})
    restarted = Store(store.root)
    seed(restarted)
    assert restarted.get(original.id) == changed
    assert restarted.all_evidence(original.id) == evidence
    with restarted.connect() as db:
        assert tuple(db.execute("SELECT request,report,updated_at FROM runs WHERE id=?", (original.id,)).fetchone()) == raw
    reset = restarted.set_metadata(original.id, RunMetadataPatch(label="   "))
    assert reset.label is None and reset.archived
    assert not restarted.set_metadata(original.id, RunMetadataPatch(archived=False)).archived


def test_archive_filters_counts_and_pagination_but_keeps_direct_access(store):
    for run_id in ("example-msft", "example-aapl"):
        store.set_metadata(run_id, RunMetadataPatch(archived=True))
    current, archived = store.history(), store.history(archived=True)
    assert current["total"] == 4 and archived["total"] == 2
    assert {item["id"] for item in archived["items"]} == {"example-msft", "example-aapl"}
    assert not any(item["archived"] for item in current["items"])
    assert store.history(limit=1, offset=1, archived=True)["items"] == archived["items"][1:2]
    assert store.get("example-msft").report
    assert store.evidence("example-msft", "fixture-MSFT-annual").synthetic


def test_existing_database_gets_metadata_without_rewriting_runs(store):
    with store.connect() as db:
        original = [tuple(row) for row in db.execute("SELECT * FROM runs ORDER BY id")]
        db.execute("DROP TABLE run_metadata")
    reopened = Store(store.root)
    assert reopened.get("example-msft").label is None
    assert not reopened.get("example-msft").archived
    reopened.set_metadata("example-msft", RunMetadataPatch(label="Legacy report"))
    with reopened.connect() as db:
        assert [tuple(row) for row in db.execute("SELECT * FROM runs ORDER BY id")] == original


def test_organizing_active_run_preserves_idempotency_and_single_worker_guard(store):
    request = RunRequest(mode="frozen", ticker="MSFT", cutoff=FIXTURE_CUTOFF, source_run_id="example-msft", model_analysis=False)
    run_id, created = store.accept(request, "organize-active")
    assert created
    store.set_metadata(run_id, RunMetadataPatch(label="In progress", archived=True))
    assert store.accept(request, "organize-active") == (run_id, False)
    with pytest.raises(DomainError, match="already active"):
        store.accept(request, "another-submission")
    store.update(run_id, status="completed", report=store.get("example-msft").report)
    assert store.get(run_id).label == "In progress" and store.get(run_id).archived


def test_archived_source_keeps_replay_and_frozen_validation(store, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Organizing or replaying a report called a provider")
    monkeypatch.setattr("research_assistant.application.OpenAI", forbidden)
    monkeypatch.setattr("research_assistant.application.retrieve_company", forbidden)
    store.set_metadata("example-msft", RunMetadataPatch(label="Saved source", archived=True))
    app = Application(store)
    try:
        request = RunRequest(mode="replay", ticker="MSFT", cutoff=FIXTURE_CUTOFF, source_run_id="example-msft")
        app.validate_source(request)
        run_id, _ = store.accept(request, "replay-archived")
        app.execute(run_id)
        result = store.get(run_id)
        assert result.status == "completed" and result.report == store.get("example-msft").report
        assert result.label is None and not result.archived
        app.validate_source(request.model_copy(update={"mode": "frozen"}))
    finally:
        app.close()


@pytest.mark.parametrize("body", [{}, {"report": {}}, {"label": "x" * 121}, {"label": 12}, {"archived": None}, {"archived": "false"}])
def test_metadata_api_rejects_invalid_or_research_edits(tmp_path, body):
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as client:
        before = client.get("/api/runs/example-msft").json()
        assert client.patch("/api/runs/example-msft", json=body).status_code == 422
        assert client.get("/api/runs/example-msft").json() == before


def test_metadata_api_validates_local_access_and_reports_missing_runs(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as client:
        url = "/api/runs/example-msft"
        assert client.patch(url, json={"archived": True}, headers={"Origin": "https://other.invalid"}).status_code == 403
        assert client.patch(url, content='{"archived":true}', headers={"Content-Type": "text/plain"}).status_code == 415
        assert client.patch("/api/runs/missing", json={"label": "Absent"}).status_code == 404
        result = client.patch(url, json={"label": " <b>My report</b> ", "archived": True})
        assert result.status_code == 200 and result.json()["label"] == "<b>My report</b>"
        assert result.json()["archived"] is True
        assert client.get("/api/runs").json()["total"] == 5
        assert client.get("/api/runs?archived=true").json()["total"] == 1
        assert client.patch(url, json={"label": None}).json()["label"] is None
