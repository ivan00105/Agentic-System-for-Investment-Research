from fastapi.testclient import TestClient

from research_assistant.api import create_app
from research_assistant.data import prices_tiingo, providers


def by_kind(status):
    return {kind["kind"]: kind for kind in status}


def provider(kind, name):
    return next(p for p in kind["providers"] if p["name"] == name)


def test_zero_configuration_degrades_to_not_configured_and_tier_zero_prices():
    kinds = by_kind(providers.status({}))
    assert set(kinds) == {"fundamentals", "filings", "identity", "prices", "llm"}
    sec = provider(kinds["fundamentals"], "sec_companyfacts")
    assert (sec["status"], sec["missing_env"], sec["tier"]) == ("not_configured", ["SEC_USER_AGENT"], 0)
    assert kinds["fundamentals"]["active"] is None
    assert provider(kinds["prices"], "tiingo")["status"] == "not_configured"
    assert provider(kinds["prices"], "yfinance")["status"] == "ready"
    assert kinds["prices"]["active"] == "yfinance"
    assert kinds["llm"]["providers"][0]["status"] == "not_configured"


def test_keys_activate_providers_in_priority_order(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Fieldnote test@example.com")
    monkeypatch.setenv("TIINGO_API_KEY", "key")
    kinds = by_kind(providers.status({}))
    assert kinds["fundamentals"]["active"] == "sec_companyfacts"
    assert provider(kinds["fundamentals"], "sec_companyfacts")["status"] == "configured"
    assert [p["name"] for p in kinds["prices"]["providers"]] == ["tiingo", "yfinance"]
    assert kinds["prices"]["active"] == "tiingo"
    monkeypatch.setenv("PRICE_PROVIDERS", "yfinance,tiingo")
    assert by_kind(providers.status({}))["prices"]["active"] == "yfinance"


def test_failed_check_is_reported_not_raised(monkeypatch):
    def broken():
        raise RuntimeError("401 bad key")
    monkeypatch.setattr(prices_tiingo, "check", broken)
    result = providers.run_check("tiingo")
    assert result == {"ok": False, "message": "RuntimeError: 401 bad key"}
    tiingo = provider(by_kind(providers.status({"tiingo": result}))["prices"], "tiingo")
    assert tiingo["status"] == "check_failed" and tiingo["last_check"]["message"].endswith("bad key")


def test_status_endpoints(tmp_path, monkeypatch):
    monkeypatch.setattr(prices_tiingo, "check", lambda: "Tiingo accepted the API key.")
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as client:
        kinds = by_kind(client.get("/api/status").json()["kinds"])
        assert kinds["prices"]["active"] == "yfinance"
        checked = client.post("/api/status/tiingo/check", json={})
        assert checked.status_code == 200
        tiingo = provider(by_kind(checked.json()["kinds"])["prices"], "tiingo")
        assert tiingo["last_check"]["ok"] and "checked_at" in tiingo["last_check"]
        assert client.post("/api/status/model/check", json={}).status_code == 404
