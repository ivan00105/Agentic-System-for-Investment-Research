import httpx
from fake_llm import FakeClient, reply
from fastapi.testclient import TestClient
from openai import AuthenticationError

from research_assistant import model_access
from research_assistant.api import create_app
from research_assistant.data import prices_tiingo, providers


def by_kind(status):
    return {kind["kind"]: kind for kind in status}


def provider(kind, name):
    return next(p for p in kind["providers"] if p["name"] == name)


def openrouter(monkeypatch, key="test-key"):
    monkeypatch.setenv("RESEARCH_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("RESEARCH_MODEL", "test/model")
    monkeypatch.setenv("OPENROUTER_API_KEY", key)


def scripted_model(monkeypatch, *script):
    client = FakeClient(*script)
    monkeypatch.setattr(model_access, "OpenAI", lambda **kwargs: client)
    return client


def test_zero_configuration_degrades_to_not_configured_and_tier_zero_prices():
    kinds = by_kind(providers.status({}))
    assert list(kinds) == ["filings", "fundamentals", "identity", "prices", "macro", "llm"]
    assert kinds["prices"]["label"] == "Daily prices" and kinds["prices"]["purpose"]
    sec = provider(kinds["fundamentals"], "sec_companyfacts")
    assert (sec["status"], sec["missing_env"], sec["tier"], sec["problem"]) == ("not_configured", ["SEC_USER_AGENT"], 0, None)
    assert kinds["fundamentals"]["active"] is None
    assert provider(kinds["prices"], "tiingo")["status"] == "not_configured"
    assert provider(kinds["prices"], "yfinance")["status"] == "ready"
    assert kinds["prices"]["active"] == "yfinance"
    llm = kinds["llm"]
    assert [p["name"] for p in llm["providers"]] == ["openrouter", "openai", "compatible"]
    assert {p["status"] for p in llm["providers"]} == {"not_configured"} and llm["active"] is None
    # OpenAI is the default service, so only OpenRouter asks for the selector.
    assert provider(llm, "openrouter")["missing_env"] == ["RESEARCH_MODEL_PROVIDER=openrouter", "RESEARCH_MODEL", "OPENROUTER_API_KEY"]
    assert provider(llm, "openai")["missing_env"] == ["RESEARCH_MODEL", "OPENAI_API_KEY"]


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


def test_only_the_selected_model_service_is_active(monkeypatch):
    openrouter(monkeypatch)
    llm = by_kind(providers.status({}))["llm"]
    assert llm["active"] == "openrouter"
    assert provider(llm, "openrouter")["status"] == "configured" and provider(llm, "openrouter")["configured"]
    assert not provider(llm, "openai")["configured"]
    assert provider(llm, "openai")["missing_env"] == ["RESEARCH_MODEL_PROVIDER=openai", "OPENAI_API_KEY"]
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    llm = by_kind(providers.status({}))["llm"]
    assert llm["active"] is None
    assert provider(llm, "openrouter")["problem"].startswith("Remove OPENAI_BASE_URL")


def test_a_set_but_invalid_sec_user_agent_says_why(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Fieldnote")
    sec = provider(by_kind(providers.status({}))["filings"], "sec_archives")
    assert sec["status"] == "not_configured" and sec["missing_env"] == []
    assert "contact email" in sec["problem"]


def test_failed_check_is_reported_not_raised(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "key")
    def broken():
        raise RuntimeError("401 bad key")
    monkeypatch.setattr(prices_tiingo, "check", broken)
    result = providers.run_check("tiingo")
    assert result == {"ok": False, "message": "RuntimeError: 401 bad key"}
    tiingo = provider(by_kind(providers.status({"tiingo": result}))["prices"], "tiingo")
    assert tiingo["status"] == "check_failed" and tiingo["last_check"]["message"].endswith("bad key")


def test_model_check_sends_one_tool_request_like_an_agent(monkeypatch):
    openrouter(monkeypatch)
    client = scripted_model(monkeypatch, reply(tool_calls=[("confirm", {})]))
    assert providers.run_check("openrouter") == {"ok": True, "message": "OpenRouter answered with fake-model and called the test tool."}
    sent = client.requests[0]
    assert sent["model"] == "test/model" and sent["tools"] == [model_access.CHECK_TOOL]
    assert sent["extra_body"]["provider"] == {"require_parameters": True, "allow_fallbacks": True}


def test_model_check_fails_without_a_tool_call_or_with_a_rejected_key(monkeypatch):
    openrouter(monkeypatch, key="secret-key-123")
    scripted_model(monkeypatch, reply("OK"))
    result = providers.run_check("openrouter")
    assert not result["ok"] and "did not call the test tool" in result["message"]
    rejected = httpx.Response(401, request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))
    scripted_model(monkeypatch, AuthenticationError("Bad key secret-key-123", response=rejected, body=None))
    result = providers.run_check("openrouter")
    assert result == {"ok": False, "message": "Model authentication or access was rejected. Check the selected provider "
                                              "credentials and permissions. (HTTP 401)"}


def test_status_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "secret-tiingo-key")
    monkeypatch.setattr(prices_tiingo, "check", lambda: "Tiingo accepted the API key.")
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as client:
        shown = client.get("/api/status")
        assert "secret-tiingo-key" not in shown.text
        assert by_kind(shown.json()["kinds"])["prices"]["active"] == "tiingo"
        checked = client.post("/api/status/tiingo/check", json={})
        assert checked.status_code == 200 and "secret-tiingo-key" not in checked.text
        tiingo = provider(by_kind(checked.json()["kinds"])["prices"], "tiingo")
        assert tiingo["last_check"]["ok"] and "checked_at" in tiingo["last_check"]
        assert client.post("/api/status/nothing/check", json={}).status_code == 404


def test_an_unconfigured_provider_is_not_tested(tmp_path, monkeypatch):
    scripted_model(monkeypatch)  # an empty script: any model call fails the test
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as client:
        refused = client.post("/api/status/openrouter/check", json={})
        assert refused.status_code == 409
        assert refused.json()["error"]["message"] == ("OpenRouter is not configured yet. Set RESEARCH_MODEL_PROVIDER=openrouter, "
                                                      "RESEARCH_MODEL, OPENROUTER_API_KEY in .env. Restart the server after changing .env.")
        openrouter_entry = provider(by_kind(client.get("/api/status").json()["kinds"])["llm"], "openrouter")
        assert openrouter_entry["last_check"] is None and openrouter_entry["status"] == "not_configured"


def test_model_check_endpoint_remembers_a_failure(tmp_path, monkeypatch):
    openrouter(monkeypatch, key="secret-key-123")
    scripted_model(monkeypatch, reply("OK"))
    with TestClient(create_app(tmp_path), base_url="http://localhost:8000") as client:
        checked = client.post("/api/status/openrouter/check", json={})
        assert checked.status_code == 200 and "secret-key-123" not in checked.text
        llm = by_kind(client.get("/api/status").json()["kinds"])["llm"]
        assert provider(llm, "openrouter")["status"] == "check_failed"
        assert llm["active"] == "openrouter"
