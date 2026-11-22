"""Explicit model credentials and request policy; configuration never probes a provider."""

import ipaddress
import json
import os
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)

from . import config
from .contracts import DomainError


@dataclass(frozen=True)
class ModelSource:
    id: str
    label: str
    provider: Literal["openai", "openrouter", "compatible"]
    model: str
    configured: bool
    error: str | None = None


@dataclass(frozen=True)
class ModelSettings:
    provider: Literal["openai", "openrouter", "compatible"]
    label: str
    model: str | None
    api_key: str | None = field(repr=False)
    base_url: str | None = field(repr=False)
    error: str | None = None
    source_id: str = "default"
    sources: tuple["ModelSource", ...] = ()
    role_routes: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model and not self.error)

    @property
    def client_kwargs(self) -> dict:
        # No max_retries override: the SDK default retries 429/5xx and connection errors.
        kwargs = {
            "api_key": self.api_key,
            "base_url": self.base_url,
        }
        if self.provider == "openrouter":
            # Empty values suppress the SDK's OPENAI_ORG_ID/OPENAI_PROJECT_ID defaults.
            kwargs.update(organization="", project="")
        return kwargs

    def request_kwargs(self, fallbacks: bool = False) -> dict:
        # fallbacks: let OpenRouter move to another host of the same model when one is rate-limited.
        # Agents use it (the serving host is traced per call); baseline A keeps a single host.
        kwargs = {"store": False}
        if self.provider == "openrouter":
            kwargs["extra_body"] = {
                "provider": {"require_parameters": True, "allow_fallbacks": fallbacks}
            }
        return kwargs

    def agent_kwargs(self) -> dict:
        """What every agent model call sends: host fallback, plus the decoding settings config.py pins (none by default)."""
        pinned = {name: value for name, value in decoding().items() if value is not None}
        return self.request_kwargs(fallbacks=True) | pinned

    def metadata(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model,
            "schema_version": "financial-review-v3",
        }

    def with_routes(self, routes: dict[str, str] | None) -> "ModelSettings":
        return ModelSettings(self.provider, self.label, self.model, self.api_key, self.base_url, self.error,
                             self.source_id, self.sources, dict(routes or {}))

    def for_role(self, role: str) -> "ModelSettings":
        source_id = self.role_routes.get(role)
        if not source_id:
            return self
        return resolve_model_source(source_id, fallback=self)


def decoding() -> dict:
    """The agents' decoding settings from config.py. None means none is sent, so the provider's default applies."""
    return {"temperature": config.AGENT_TEMPERATURE, "top_p": config.AGENT_TOP_P, "seed": config.AGENT_SEED}


def decoding_record() -> dict:
    """The decoding settings as a trace records them, so a run says what it ran with even when nothing is pinned."""
    return {name: "provider default" if value is None else value for name, value in decoding().items()}


def _setting(name: str) -> str | None:
    return os.getenv(name, "").strip() or None


def _valid_endpoint(value: str) -> bool:
    try:
        endpoint = urlsplit(value)
        if (
            not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
            or "?" in value
            or "#" in value
            or any(character.isspace() or ord(character) < 32 for character in value)
        ):
            return False
        _ = endpoint.port  # Reject malformed ports during configuration loading.
        if endpoint.scheme == "https":
            return True
        if endpoint.scheme != "http":
            return False
        if endpoint.hostname.lower() == "localhost":
            return True
        return ipaddress.ip_address(endpoint.hostname).is_loopback
    except ValueError:
        return False


def load_model_settings() -> ModelSettings:
    provider = (_setting("RESEARCH_MODEL_PROVIDER") or "openai").lower()
    model = _setting("RESEARCH_MODEL")
    custom_url = _setting("OPENAI_BASE_URL")
    if provider not in {"openai", "openrouter", "compatible"}:
        return ModelSettings("openai", "Model access", model, None, None,
                             "RESEARCH_MODEL_PROVIDER must be openai, openrouter or compatible.")
    if provider == "openrouter":
        error = None
        if custom_url:
            error = "Remove OPENAI_BASE_URL when selecting OpenRouter; its endpoint is fixed."
        elif model and (
            model.lower().split(":", 1)[0] in {"openrouter/auto", "openrouter/free"}
            or "online" in model.lower().split(":")[1:]
        ):
            error = "Choose an explicit OpenRouter model without automatic routing or online search."
        return ModelSettings("openrouter", "OpenRouter", model,
                             _setting("OPENROUTER_API_KEY"), "https://openrouter.ai/api/v1", error)
    if custom_url or provider == "compatible":
        error = None
        if not custom_url:
            error = "Set OPENAI_BASE_URL for the compatible provider."
        elif not _valid_endpoint(custom_url):
            error = "OPENAI_BASE_URL must use HTTPS (or loopback HTTP) without credentials, query or fragment."
        return ModelSettings("compatible", "OpenAI-compatible", model,
                             _setting("OPENAI_API_KEY"), custom_url, error)
    settings = ModelSettings("openai", "OpenAI", model,
                             _setting("OPENAI_API_KEY"), "https://api.openai.com/v1")
    return settings


def _source_settings(entry: dict) -> tuple[ModelSource, ModelSettings]:
    source_id = str(entry.get("id", "")).strip()
    label = str(entry.get("label", "")).strip()
    provider = str(entry.get("provider", "")).strip().lower()
    model = str(entry.get("model", "")).strip()
    if not source_id or not label or provider not in {"openai", "openrouter", "compatible"} or not model:
        return (ModelSource(source_id or "invalid", label or "Invalid model source",
                            provider if provider in {"openai", "openrouter", "compatible"} else "compatible",
                            model, False, "Each source needs id, label, provider and model."),
                ModelSettings("compatible", "Invalid model source", model, None, None,
                              "Invalid model source.", source_id))
    key_env = str(entry.get("api_key_env", "")).strip()
    if not key_env:
        key_env = "OPENROUTER_API_KEY" if provider == "openrouter" else "OPENAI_API_KEY"
    api_key = _setting(key_env)
    custom_url = str(entry.get("base_url", "")).strip() or (_setting("OPENAI_BASE_URL") if provider == "compatible" else None)
    error = None
    if provider == "openrouter":
        base_url = "https://openrouter.ai/api/v1"
        if custom_url:
            error = "OpenRouter sources must not set base_url."
    elif provider == "compatible":
        base_url = custom_url
        if not base_url:
            error = f"Set base_url or OPENAI_BASE_URL for source {source_id}."
        elif not _valid_endpoint(base_url):
            error = f"Source {source_id} has an invalid base_url."
    else:
        base_url = "https://api.openai.com/v1"
    settings = ModelSettings(provider, label, model, api_key, base_url, error, source_id)
    source = ModelSource(source_id, label, provider, model, settings.configured, error)
    return source, settings


def load_model_sources() -> tuple[ModelSource, ...]:
    """The primary setting and optional RESEARCH_MODEL_SOURCES are both usable model choices."""
    primary = load_model_settings()
    sources = [ModelSource("default", primary.label, primary.provider, primary.model or "",
                           primary.configured, primary.error)]
    raw = _setting("RESEARCH_MODEL_SOURCES")
    if not raw:
        return tuple(sources)
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        sources.append(ModelSource("invalid", "Invalid model sources", "compatible", "", False,
                                   "RESEARCH_MODEL_SOURCES must be a JSON array."))
        return tuple(sources)
    if not isinstance(entries, list):
        sources.append(ModelSource("invalid", "Invalid model sources", "compatible", "", False,
                                   "RESEARCH_MODEL_SOURCES must be a JSON array."))
        return tuple(sources)
    seen = {"default"}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source, _ = _source_settings(entry)
        if source.id in seen:
            continue
        seen.add(source.id)
        sources.append(source)
    return tuple(sources)


def resolve_model_source(source_id: str, fallback: ModelSettings | None = None) -> ModelSettings:
    primary = fallback or load_model_settings()
    if source_id == "default":
        return primary
    raw = _setting("RESEARCH_MODEL_SOURCES")
    if raw:
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError:
            entries = []
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and str(entry.get("id", "")).strip() == source_id:
                    _, settings = _source_settings(entry)
                    settings = settings.with_routes(primary.role_routes)
                    return settings
    if fallback is not None:
        return fallback
    return load_model_settings()


def make_model_client(settings: ModelSettings):
    """Create a provider-specific client for a routed role; cli.model_client remains the testable factory."""
    return OpenAI(**settings.client_kwargs, max_retries=config.AGENT_MODEL_RETRIES)


def client_for_role(base_client, base_settings: ModelSettings, role: str):
    routed = base_settings.for_role(role)
    if routed.source_id == base_settings.source_id and routed.provider == base_settings.provider and routed.model == base_settings.model:
        return base_client, routed
    return make_model_client(routed), routed


def safe_model_error(exc: Exception) -> DomainError:
    """Translate failures without reflecting provider messages, headers or credentials."""
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    if isinstance(error, dict) and error.get("code") in ("context_length_exceeded", "context_window_exceeded", "input_too_long"):
        return DomainError("The complete evidence exceeds the selected model's input context. Evidence was not silently truncated. Choose a model with a larger context or explicitly narrow the source selection.", "model_context_limit", 502)
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return DomainError("Model authentication or access was rejected. Check the selected provider credentials and permissions.", "model_authentication", 502)
    if isinstance(exc, RateLimitError):
        return DomainError("The model provider rate limit was still reached after automatic retries. Saved results remain available; retry later.", "model_rate_limit", 502)
    if isinstance(exc, (APITimeoutError, TimeoutError)):
        return DomainError("The model request still timed out after automatic retries. Saved results remain available.", "model_timeout", 502)
    if isinstance(exc, (BadRequestError, APIResponseValidationError, ValueError)):
        return DomainError("The model request or structured response was incompatible with the required schema. Saved results remain available.", "model_schema", 502)
    if isinstance(exc, (NotFoundError, APIConnectionError)):
        return DomainError("The selected model or provider endpoint is unavailable. Saved results remain available; retry explicitly later.", "model_unavailable", 502)
    if isinstance(exc, APIStatusError):
        if exc.status_code == 402:
            return DomainError("The model provider requires payment or additional credits. Check the selected provider account.", "model_unavailable", 502)
        return DomainError("The model provider could not complete the request. Saved results remain available; retry explicitly later.", "model_unavailable", 502)
    return DomainError("Model request failed. Saved results remain available.", "model_failed", 502)


CHECK_TOOL = {"type": "function", "function": {
    "name": "confirm", "description": "Confirm that you can call tools.", "parameters": {"type": "object", "properties": {}}}}


def check_model() -> str:
    """One short request with one tool, sent the way agent runs send theirs: it proves the key, the model and
    tool calling. It costs a fraction of a cent, so the Setup page asks for no consent."""
    settings = load_model_settings()
    try:
        with OpenAI(**settings.client_kwargs) as client:
            reply = client.chat.completions.create(
                model=settings.model, messages=[{"role": "user", "content": "Call the confirm tool."}],
                tools=[CHECK_TOOL], **settings.request_kwargs(fallbacks=True))
    except OpenAIError as exc:
        error, status = safe_model_error(exc), getattr(exc, "status_code", None)
        raise DomainError(f"{error} (HTTP {status})" if status else str(error), error.code, error.status) from None
    served = reply.model or settings.model
    if not (reply.choices and reply.choices[0].message.tool_calls):
        raise DomainError(f"{settings.label} answered with {served} but did not call the test tool. "
                          "Agent runs need a model that calls tools.", "model_schema", 502)
    return f"{settings.label} answered with {served} and called the test tool."
