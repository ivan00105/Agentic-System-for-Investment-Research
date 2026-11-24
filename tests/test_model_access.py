"""Model configuration and error policy use no live provider requests."""

from dataclasses import FrozenInstanceError

import httpx
import pytest
from openai import (
    APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError,
    BadRequestError, NotFoundError, OpenAIError, PermissionDeniedError, RateLimitError,
)

from research_assistant import config
from research_assistant.model_access import (client_for_role, decoding_record, load_model_settings, load_model_sources,
                                             load_provider_settings, resolve_model_source, safe_model_error)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    for name in ("RESEARCH_MODEL_PROVIDER", "RESEARCH_MODEL", "OPENAI_API_KEY", "OPENAI_MODEL",
                 "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENAI_BASE_URL",
                 "COMPATIBLE_BASE_URL", "COMPATIBLE_MODEL", "COMPATIBLE_API_KEY", "RESEARCH_MODEL_SOURCES"):
        monkeypatch.delenv(name, raising=False)


def configure(monkeypatch, **values):
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return load_model_settings()


def test_legacy_openai_settings_are_explicit_and_private(monkeypatch):
    settings = configure(monkeypatch, OPENAI_API_KEY=" secret-openai ", RESEARCH_MODEL=" gpt-example ")
    assert settings.configured
    assert settings.provider == "openai"
    assert settings.label == "OpenAI"
    assert settings.model == "gpt-example"
    assert settings.client_kwargs == {"api_key": "secret-openai", "base_url": "https://api.openai.com/v1"}
    assert settings.request_kwargs() == settings.request_kwargs(fallbacks=True) == {"store": False}
    assert settings.metadata() == {"provider": "openai", "model": "gpt-example", "schema_version": "financial-review-v3"}
    assert "secret-openai" not in repr(settings)
    assert "https://api.openai.com" not in repr(settings)
    with pytest.raises(FrozenInstanceError):
        settings.model = "changed"


@pytest.mark.parametrize("values", [
    {}, {"OPENAI_API_KEY": " "}, {"OPENAI_API_KEY": "secret", "RESEARCH_MODEL": " \t "},
    {"OPENROUTER_API_KEY": "router-secret", "RESEARCH_MODEL": "model"},
])
def test_missing_or_whitespace_settings_are_not_configured(monkeypatch, values):
    assert not configure(monkeypatch, **values).configured


def test_openrouter_uses_only_its_key_and_pins_request_policy(monkeypatch):
    settings = configure(monkeypatch, RESEARCH_MODEL_PROVIDER=" OpenRouter ",
                         RESEARCH_MODEL=" vendor/model:free ", OPENROUTER_API_KEY=" router-secret ",
                         OPENAI_API_KEY="openai-secret", OPENAI_ORG_ID="openai-org", OPENAI_PROJECT_ID="openai-project")
    assert settings.configured
    assert settings.provider == "openrouter"
    assert settings.client_kwargs == {"api_key": "router-secret", "base_url": "https://openrouter.ai/api/v1", "organization": "", "project": ""}
    assert settings.request_kwargs() == {"store": False, "extra_body": {"provider": {"require_parameters": True, "allow_fallbacks": False}}}
    # Agents let OpenRouter fall back to another host of the same model; baseline A keeps one host.
    assert settings.request_kwargs(fallbacks=True)["extra_body"]["provider"]["allow_fallbacks"] is True
    assert settings.metadata()["model"] == "vendor/model:free"
    assert "router-secret" not in repr(settings)


def test_multiple_model_sources_and_role_routing(monkeypatch):
    monkeypatch.setenv("RESEARCH_MODEL_PROVIDER", "openrouter")
    monkeypatch.setenv("RESEARCH_MODEL", "primary/model")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("RESEARCH_MODEL_SOURCES",
                       '[{"id":"openai-fast","label":"OpenAI Fast","provider":"openai","model":"gpt-fast","api_key_env":"OPENAI_API_KEY"}]')
    sources = load_model_sources()
    assert [source.id for source in sources] == ["default", "openai-fast"]
    routed = resolve_model_source("openai-fast")
    assert routed.provider == "openai"
    assert routed.model == "gpt-fast"
    assert routed.api_key == "openai-key"
    settings = load_model_settings().with_routes({"fundamentals": "openai-fast", "filings": "default"})
    assert settings.for_role("fundamentals").model == "gpt-fast"
    assert settings.for_role("filings").model == "primary/model"


def test_multiple_builtin_providers_configured_together_without_json(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "deepseek/deepseek-v4.1-flash")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")
    monkeypatch.setenv("COMPATIBLE_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("COMPATIBLE_MODEL", "qwen3:8b")
    monkeypatch.setenv("COMPATIBLE_API_KEY", "ollama")

    assert load_provider_settings("openrouter").configured
    assert load_provider_settings("openai").configured
    assert load_provider_settings("compatible").configured
    sources = load_model_sources()
    assert [s.id for s in sources] == ["default", "openrouter", "compatible"]
    assert resolve_model_source("openrouter").model == "deepseek/deepseek-v4.1-flash"
    assert resolve_model_source("compatible").base_url == "http://localhost:11434/v1"
    assert resolve_model_source("openai").model == "gpt-5-mini"

    seen_clients = []
    settings = load_model_settings().with_routes({"fundamentals": "openrouter", "critic": "compatible"})
    from dataclasses import replace
    settings = replace(settings, client_factory=lambda s: seen_clients.append((s.provider, s.model, s.base_url)) or object())
    base_client = object()
    c_coord, s_coord = client_for_role(base_client, settings, "coordinator")
    c_fund, s_fund = client_for_role(base_client, settings, "fundamentals")
    c_critic, s_critic = client_for_role(base_client, settings, "critic")
    assert c_coord is base_client and s_coord.provider == "openai"
    assert c_fund is not base_client and s_fund.provider == "openrouter"
    assert c_critic is not base_client and s_critic.provider == "compatible"
    assert seen_clients == [
        ("openrouter", "deepseek/deepseek-v4.1-flash", "https://openrouter.ai/api/v1"),
        ("compatible", "qwen3:8b", "http://localhost:11434/v1"),
    ]


def test_openrouter_source_in_json_rejects_auto_and_online(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-key")
    monkeypatch.setenv("RESEARCH_MODEL_SOURCES",
                       '[{"id":"bad-auto","label":"Auto","provider":"openrouter","model":"openrouter/auto"}]')
    sources = {s.id: s for s in load_model_sources()}
    assert not sources["bad-auto"].configured
    assert "automatic routing" in (sources["bad-auto"].error or "")


def test_agents_send_only_the_decoding_settings_config_pins(monkeypatch):
    settings = configure(monkeypatch, RESEARCH_MODEL_PROVIDER="openrouter", RESEARCH_MODEL="m", OPENROUTER_API_KEY="k")
    routed = settings.request_kwargs(fallbacks=True)
    routed["extra_body"]["provider"]["ignore"] = ["wafer"]  # config.AGENT_IGNORED_HOSTS
    assert settings.agent_kwargs() == routed
    assert decoding_record() == dict.fromkeys(("temperature", "top_p", "seed"), "provider default")
    monkeypatch.setattr(config, "AGENT_TOP_P", 0.9)
    monkeypatch.setattr(config, "AGENT_SEED", 7)
    assert settings.agent_kwargs() == routed | {"top_p": 0.9, "seed": 7}
    assert decoding_record() == {"temperature": "provider default", "top_p": 0.9, "seed": 7}


def test_openrouter_cannot_fall_back_to_openai_key(monkeypatch):
    settings = configure(monkeypatch, RESEARCH_MODEL_PROVIDER="openrouter", RESEARCH_MODEL="vendor/model", OPENAI_API_KEY="wrong-key")
    assert settings.api_key is None
    assert not settings.configured


def test_openrouter_rejects_conflicting_endpoint_without_exposing_it(monkeypatch):
    settings = configure(monkeypatch, RESEARCH_MODEL_PROVIDER="openrouter", RESEARCH_MODEL="vendor/model", OPENROUTER_API_KEY="secret", OPENAI_BASE_URL="https://user:password@example.com/private")
    assert not settings.configured
    assert settings.error
    assert "password" not in settings.error
    assert "example.com" not in repr(settings)
    assert settings.base_url == "https://openrouter.ai/api/v1"


@pytest.mark.parametrize("model", ["openrouter/auto", "openrouter/free", "openrouter/auto:free", "vendor/model:online", "vendor/model:free:online"])
def test_openrouter_rejects_implicit_routers_and_search(monkeypatch, model):
    settings = configure(monkeypatch, RESEARCH_MODEL_PROVIDER="openrouter", RESEARCH_MODEL=model, OPENROUTER_API_KEY="secret")
    assert not settings.configured
    assert settings.error


@pytest.mark.parametrize("url", ["https://gateway.example/v1", "http://localhost:8000/v1", "http://127.0.0.1:8000/v1", "http://[::1]:8000/v1"])
@pytest.mark.parametrize("provider", ["openai", "compatible"])
def test_custom_trusted_endpoint_is_identified_as_compatible(monkeypatch, url, provider):
    settings = configure(monkeypatch, RESEARCH_MODEL_PROVIDER=provider, OPENAI_BASE_URL=url, RESEARCH_MODEL="model", OPENAI_API_KEY="secret")
    assert settings.configured
    assert settings.provider == "compatible"
    assert settings.client_kwargs["base_url"] == url
    assert "base_url" not in settings.metadata()


@pytest.mark.parametrize("url", ["http://example.com/v1", "ftp://example.com/v1", "https://user:secret@example.com/v1", "https://example.com/v1?key=secret", "https://example.com/v1#secret", "https://example.com/v1?", "https://example.com:invalid/v1", "https:///v1", "https://exa mple.com/v1"])
def test_custom_endpoint_rejects_unsafe_or_malformed_values(monkeypatch, url):
    settings = configure(monkeypatch, OPENAI_BASE_URL=url, RESEARCH_MODEL="model", OPENAI_API_KEY="secret")
    assert not settings.configured
    assert settings.error
    assert "secret" not in settings.error
    assert url not in repr(settings)


@pytest.mark.parametrize("provider", ["compatible", "invalid-secret-provider"])
def test_invalid_provider_configuration_is_safe_without_startup_exception(monkeypatch, provider):
    settings = configure(monkeypatch, RESEARCH_MODEL_PROVIDER=provider, RESEARCH_MODEL="model", OPENAI_API_KEY="secret")
    assert not settings.configured
    assert settings.error
    assert "invalid-secret-provider" not in settings.error


@pytest.mark.parametrize("error_type,status,code", [
    (AuthenticationError, 401, "model_authentication"),
    (PermissionDeniedError, 403, "model_authentication"),
    (RateLimitError, 429, "model_rate_limit"),
    (BadRequestError, 400, "model_schema"),
    (NotFoundError, 404, "model_unavailable"),
    (APIStatusError, 402, "model_unavailable"),
    (APIStatusError, 503, "model_unavailable"),
])
def test_sdk_status_errors_have_safe_domain_errors(error_type, status, code):
    response = httpx.Response(status, request=httpx.Request("POST", "https://secret.example/v1"))
    error = error_type("secret-provider-message", response=response, body={"key": "secret-key"})
    safe = safe_model_error(error)
    assert safe.code == code
    assert safe.status == 502
    assert "secret" not in str(safe)


@pytest.mark.parametrize("error,code", [
    (APITimeoutError(httpx.Request("POST", "https://secret.example/v1")), "model_timeout"),
    (APIConnectionError(message="secret-provider-message", request=httpx.Request("POST", "https://secret.example/v1")), "model_unavailable"),
    (ValueError("secret-response-body"), "model_schema"),
    (OpenAIError("secret-provider-message"), "model_failed"),
    (RuntimeError("secret-api-key"), "model_failed"),
])
def test_other_errors_never_reflect_provider_details(error, code):
    safe = safe_model_error(error)
    assert safe.code == code
    assert "secret" not in str(safe)
