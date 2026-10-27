"""Model configuration and error policy use no live provider requests."""

from dataclasses import FrozenInstanceError

import httpx
import pytest
from openai import (
    APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError,
    BadRequestError, NotFoundError, OpenAIError, PermissionDeniedError, RateLimitError,
)

from research_assistant.model_access import load_model_settings, safe_model_error


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    for name in ("RESEARCH_MODEL_PROVIDER", "RESEARCH_MODEL", "OPENAI_API_KEY",
                 "OPENROUTER_API_KEY", "OPENAI_BASE_URL"):
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
    assert settings.client_kwargs == {"api_key": "secret-openai", "base_url": "https://api.openai.com/v1", "timeout": 45, "max_retries": 0}
    assert settings.request_kwargs() == {"store": False}
    assert settings.metadata() == {"provider": "openai", "model": "gpt-example", "schema_version": "financial-review-v1"}
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
    assert settings.client_kwargs == {"api_key": "router-secret", "base_url": "https://openrouter.ai/api/v1", "timeout": 45, "max_retries": 0, "organization": "", "project": ""}
    assert settings.request_kwargs() == {"store": False, "extra_body": {"provider": {"require_parameters": True, "allow_fallbacks": False}}}
    assert settings.metadata()["model"] == "vendor/model:free"
    assert "router-secret" not in repr(settings)


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
